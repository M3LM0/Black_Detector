#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess
import re
import argparse


def find_ffmpeg():
    """
    Recherche l'exécutable ffmpeg dans différents emplacements :
      1. Variable d'environnement 'FFMPEG_PATH' (peut pointer vers l'exécutable ou son dossier)
      2. Répertoire relatif 'bin' dans le dossier de l'exécutable (PyInstaller)
      3. Chemin système (via shutil.which)
    Retourne :
      Le chemin complet de ffmpeg si trouvé, sinon None.
    """
    env_path = os.getenv("FFMPEG_PATH")
    if env_path:
        if os.path.isdir(env_path):
            ffmpeg_exec = os.path.join(env_path, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        else:
            ffmpeg_exec = env_path
        if os.path.isfile(ffmpeg_exec):
            return ffmpeg_exec

    base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    bundled_ffmpeg = os.path.join(base_dir, "bin", "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if os.path.isfile(bundled_ffmpeg):
        return bundled_ffmpeg

    ffmpeg_in_path = shutil.which("ffmpeg")
    if ffmpeg_in_path:
        return ffmpeg_in_path

    return None


def find_ffprobe():
    """
    Recherche l'exécutable ffprobe dans différents emplacements, en se basant sur ffmpeg :
      1. Dans le même dossier que ffmpeg (dans 'bin' si en mode PyInstaller)
      2. Chemin système (via shutil.which)
    Retourne :
      Le chemin complet de ffprobe si trouvé, sinon None.
    """
    ffmpeg_exec = find_ffmpeg()
    if ffmpeg_exec:
        base_dir = os.path.dirname(ffmpeg_exec)
        candidate = os.path.join(base_dir, "ffprobe.exe" if os.name == "nt" else "ffprobe")
        if os.path.isfile(candidate):
            return candidate

    ffprobe_in_path = shutil.which("ffprobe")
    if ffprobe_in_path:
        return ffprobe_in_path

    return None


def get_video_duration(video_file, ffprobe_path):
    """
    Récupère la durée totale de la vidéo en secondes en utilisant ffprobe.

    Paramètres :
      video_file (str)   : Chemin vers le fichier vidéo.
      ffprobe_path (str) : Chemin complet vers l'exécutable ffprobe.

    Retourne :
      float : Durée de la vidéo en secondes.
    """
    cmd = [
        ffprobe_path,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_file
    ]
    try:
        output = subprocess.check_output(cmd, universal_newlines=True)
        duration = float(output.strip())
        return duration
    except Exception as e:
        sys.exit(f"Erreur lors de la récupération de la durée de la vidéo : {e}")


def time_str_to_seconds(time_str):
    """
    Convertit une chaîne de type 'HH:MM:SS.ss' en secondes.
    """
    try:
        parts = time_str.split(':')
        hours = float(parts[0])
        minutes = float(parts[1])
        seconds = float(parts[2])
        return hours * 3600 + minutes * 60 + seconds
    except Exception:
        return 0.0


def format_time_full(seconds):
    """
    Formate le temps en secondes au format hh:mm:ss:ms.
    Exemple : 867.799 => "00:14:27:799"
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    msecs = int((seconds - int(seconds)) * 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}:{msecs:03}"


def parse_ini_offset(ini_filepath):
    """
    Lit le fichier INI et extrait la valeur de START_TIME.
    La valeur attendue est au format, par exemple, "10h36m22.010s".

    Retourne :
      float : L'offset en secondes, ou 0 si la valeur n'est pas trouvée.
    """
    offset = 0.0
    try:
        with open(ini_filepath, 'r') as f:
            content = f.read()
        # Recherche de la valeur START_TIME dans le fichier INI
        pattern = re.compile(r'START_TIME\s*=\s*"([^"]+)"')
        match = pattern.search(content)
        if match:
            time_str = match.group(1).strip()
            # Utilisation d'un pattern pour extraire heures, minutes et secondes
            time_pattern = re.compile(r'(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?')
            time_match = time_pattern.match(time_str)
            if time_match:
                hours = float(time_match.group(1)) if time_match.group(1) else 0.0
                minutes = float(time_match.group(2)) if time_match.group(2) else 0.0
                seconds = float(time_match.group(3)) if time_match.group(3) else 0.0
                offset = hours * 3600 + minutes * 60 + seconds
    except Exception:
        offset = 0.0
    return offset


def detect_black_frames(video_file, ffmpeg_path, total_duration, duration_threshold=0.5, pic_threshold=0.98):
    """
    Utilise ffmpeg pour détecter les séquences noires dans une vidéo tout en affichant
    en temps réel la progression en pourcentage.

    Paramètres:
      video_file (str)       : Chemin vers le fichier vidéo.
      ffmpeg_path (str)      : Chemin complet vers l'exécutable ffmpeg.
      total_duration (float) : Durée totale de la vidéo en secondes.
      duration_threshold (float) : Durée minimale (en secondes) pour considérer une séquence noire.
      pic_threshold (float)  : Seuil de luminosité pour déterminer une image noire.

    Retourne:
      List[Dict] : Liste de dictionnaires décrivant les séquences noires détectées.
                  Chaque dictionnaire contient les clés 'start', 'end' et 'duration' (en secondes).
    """
    cmd = [
        ffmpeg_path,
        "-hide_banner", "-loglevel", "info",
        "-i", video_file,
        "-vf", f"blackdetect=d={duration_threshold}:pic_th={pic_threshold}",
        "-an", "-f", "null", "-"
    ]

    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, universal_newlines=True, bufsize=1)

    time_pattern = re.compile(r"time=(\d{2}:\d{2}:\d{2}\.\d+)")
    black_pattern = re.compile(r"black_start:([\d\.]+)\s+black_end:([\d\.]+)\s+black_duration:([\d\.]+)")

    black_frames = []
    try:
        for line in proc.stderr:
            line = line.strip()
            time_match = time_pattern.search(line)
            if time_match:
                current_time_str = time_match.group(1)
                current_time_sec = time_str_to_seconds(current_time_str)
                progress = (current_time_sec / total_duration) * 100
                sys.stdout.write(f"\rTraitement : {progress:.0f}%")
                sys.stdout.flush()
            black_match = black_pattern.search(line)
            if black_match:
                start, end, duration = black_match.groups()
                black_frames.append({
                    "start": float(start),
                    "end": float(end),
                    "duration": float(duration)
                })
        proc.wait()
        sys.stdout.write("\n")
    except KeyboardInterrupt:
        proc.terminate()
        sys.exit("Processus interrompu par l'utilisateur.")
    return black_frames


def main():
    parser = argparse.ArgumentParser(
        description="Détecte les séquences noires dans une vidéo en utilisant ffmpeg, avec affichage du temps au format hh:mm:ss:ms et prise en compte d'un offset défini dans un fichier INI associé."
    )
    parser.add_argument("video", help="Chemin vers le fichier vidéo à analyser")
    parser.add_argument("-d", "--duration", type=float, default=0.5,
                        help="Durée minimale (en secondes) d'une séquence noire [par défaut: 0.5]")
    parser.add_argument("-t", "--threshold", type=float, default=0.98,
                        help="Seuil de luminosité pour considérer une image comme noire [par défaut: 0.98]")
    args = parser.parse_args()

    ffmpeg_exec = find_ffmpeg()
    if not ffmpeg_exec:
        sys.exit(
            "Erreur : l'exécutable ffmpeg n'a pas été trouvé. Veuillez le placer dans le dossier 'bin' ou définir la variable d'environnement FFMPEG_PATH.")

    ffprobe_exec = find_ffprobe()
    if not ffprobe_exec:
        sys.exit(
            "Erreur : l'exécutable ffprobe n'a pas été trouvé. Veuillez le placer dans le dossier 'bin' ou ajuster la configuration.")

    # Récupérer l'offset depuis le fichier INI, si présent.
    offset = 0.0
    ini_file = args.video + ".ini"  # Par exemple, "video.ts" => "video.ts.ini"
    if os.path.exists(ini_file):
        offset = parse_ini_offset(ini_file)
        print(f"Offset START_TIME détecté : {format_time_full(offset)}")
    else:
        print("Aucun fichier INI associé trouvé. Aucune correction d'offset ne sera appliquée.")

    total_duration = get_video_duration(args.video, ffprobe_exec)
    print(f"Durée totale de la vidéo : {format_time_full(total_duration)}")

    # Détection des séquences noires (les temps sont exprimés en secondes depuis le début de la vidéo)
    results = detect_black_frames(args.video, ffmpeg_exec, total_duration,
                                  duration_threshold=args.duration, pic_threshold=args.threshold)

    if results:
        print("\nSéquences noires détectées :")
        for seq in results:
            # Appliquer l'offset aux temps de début et de fin
            debut = format_time_full(seq['start'] + offset)
            fin = format_time_full(seq['end'] + offset)
            duree = format_time_full(seq['duration'])
            print(f"Début : {debut}, Fin : {fin}, Durée : {duree}")
    else:
        print("\nAucune séquence noire détectée.")

    print(f"\nNombres de séquences détectées = {len(results)} Séquences")


if __name__ == "__main__":
    main()
