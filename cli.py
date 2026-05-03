import argparse
import math
import os
import shutil
import sys
import threading

import requests
from tqdm import tqdm

from gdrive import extract_drive_id, get_file_size, get_video_url, sanitize_filename


def download_part(url, cookies, thread_lock, start, end, part_filename, chunk_size, pbar, gp_bar, verbose):
    headers = {'Range': f'bytes={start}-{end}'}
    downloaded = 0

    if os.path.exists(part_filename):
        downloaded = os.path.getsize(part_filename)
        if downloaded > 0:
            headers['Range'] = f'bytes={start + downloaded}-{end}'
            with thread_lock:
                gp_bar.update(downloaded)
                pbar.update(downloaded)
            if verbose:
                print(f"[INFO] Resuming part {part_filename} from byte {start + downloaded}")

    if downloaded >= (end - start + 1):
        return

    s = requests.Session()
    response = s.get(url, stream=True, cookies=cookies, headers=headers)
    if response.status_code not in (200, 206):
        raise Exception(f"[ERROR] Failed to download part {part_filename}, status: {response.status_code}")

    file_mode = 'ab' if os.path.exists(part_filename) and os.path.getsize(part_filename) > 0 else 'wb'
    with open(part_filename, file_mode) as f:
        for chunk in response.iter_content(chunk_size=chunk_size):
            f.write(chunk)
            with thread_lock:
                gp_bar.update(len(chunk))
                pbar.update(len(chunk))
            downloaded += len(chunk)
            if downloaded >= (end - start + 1):
                break


def merge_parts(part_files, output_filename, verbose):
    if verbose:
        print(f"[INFO] Merging {len(part_files)} parts into {output_filename}")

    missing = [pf for pf in part_files if not os.path.exists(pf)]
    if missing:
        print(f"[ERROR] Missing parts: {missing}")
        return

    with open(output_filename, 'wb') as outfile:
        for part_file in part_files:
            if verbose:
                print(f"[INFO] Merging {part_file}")
            with open(part_file, 'rb') as pf:
                shutil.copyfileobj(pf, outfile)

    for part_file in part_files:
        os.remove(part_file)

    if verbose:
        print("[INFO] Merge complete. Cleaned up part files.")


def download_file(url, cookies, filename, chunk_size, num_threads, verbose):
    total_size = get_file_size(url, cookies)
    if num_threads == 1 or total_size == 0:
        if total_size == 0:
            print("[WARN] Could not determine file size. Falling back to single-threaded download.")
        download_single_threaded(url, cookies, filename, chunk_size, verbose)
        return

    if verbose:
        print(f"[INFO] Total file size: {total_size} bytes")
        print(f"[INFO] Downloading with {num_threads} threads")

    part_size = math.ceil(total_size / num_threads)
    part_files = []
    threads = []
    thread_lock = threading.Lock()
    errors = []
    errors_lock = threading.Lock()

    gp_bar = tqdm(unit='B', unit_scale=True, desc="Download Progress", total=total_size, position=0)
    pbars = [
        tqdm(
            unit='B', unit_scale=True,
            desc=f"Downloading Part {i + 1}",
            total=min(part_size, total_size - i * part_size),
            position=i + 1,
        )
        for i in range(num_threads)
    ]

    def make_wrapper(i, start, end, part_filename):
        def wrapper():
            try:
                download_part(url, cookies, thread_lock, start, end, part_filename, chunk_size, pbars[i], gp_bar, verbose)
            except Exception as e:
                with errors_lock:
                    errors.append(e)
        return wrapper

    for i in range(num_threads):
        start = i * part_size
        end = min(start + part_size - 1, total_size - 1)
        part_filename = f"{filename}.part{i}"
        part_files.append(part_filename)
        t = threading.Thread(target=make_wrapper(i, start, end, part_filename), daemon=True)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    gp_bar.close()
    for pbar in pbars:
        pbar.close()

    if errors:
        print("[ERROR] One of the parts failed. Check the console for details. Exiting...")
        return

    downloaded_total = sum(os.path.getsize(pf) for pf in part_files if os.path.exists(pf))
    if downloaded_total < total_size:
        print(f"[ERROR] Download incomplete: got {downloaded_total}/{total_size} bytes.")
        return

    merge_parts(part_files, filename, verbose)
    print(f"\n{filename} downloaded successfully.")


def download_single_threaded(url, cookies, filename, chunk_size, verbose):
    headers = {}
    file_mode = 'wb'
    downloaded_size = 0

    if os.path.exists(filename):
        downloaded_size = os.path.getsize(filename)
        headers['Range'] = f"bytes={downloaded_size}-"
        file_mode = 'ab'

    if verbose:
        print(f"[INFO] Starting single-threaded download from {url}")

    response = requests.get(url, stream=True, cookies=cookies, headers=headers)
    if response.status_code in (200, 206):
        total_size = int(response.headers.get('content-length', 0)) + downloaded_size
        with open(filename, file_mode) as file:
            with tqdm(total=total_size, initial=downloaded_size, unit='B', unit_scale=True, desc=filename, file=sys.stdout) as pbar:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        file.write(chunk)
                        pbar.update(len(chunk))
        print(f"\n{filename} downloaded successfully.")
    else:
        print(f"Error downloading {filename}, status code: {response.status_code}")


def main(video_id_or_url, output_file=None, chunk_size=1024, num_threads=4, verbose=False):
    video_id = extract_drive_id(video_id_or_url)

    if verbose:
        print(f"[INFO] Extracted video ID: {video_id}")

    drive_url = f'https://drive.google.com/u/0/get_video_info?docid={video_id}&drive_originator_app=303'

    if verbose:
        print(f"[INFO] Accessing {drive_url}")

    response = requests.get(drive_url)
    cookies = response.cookies.get_dict()
    video, title = get_video_url(response.text)

    if verbose:
        print(f"[INFO] Video URL: {video}")
        print(f"[INFO] Video Title: {title}")

    filename = sanitize_filename(output_file if output_file else title)

    if video:
        download_file(video, cookies, filename, chunk_size, num_threads, verbose)
    else:
        print("Unable to retrieve the video URL. Ensure the video ID is correct and accessible.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Script to download videos from Google Drive.")
    parser.add_argument("video_id", type=str, help="The video ID from Google Drive or a full Google Drive URL.")
    parser.add_argument("-o", "--output", type=str, help="Optional output file name.")
    parser.add_argument("-c", "--chunk_size", type=int, default=1024, help="Chunk size in bytes (default: 1024).")
    parser.add_argument("-t", "--threads", type=int, default=4, choices=range(1, 17), help="Number of threads (1-16, default: 4).")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose mode.")
    parser.add_argument("--version", action="version", version="%(prog)s 1.1.0")

    args = parser.parse_args()
    main(args.video_id, args.output, args.chunk_size, args.threads, args.verbose)
