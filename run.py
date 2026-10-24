"""Start Paper Radio's custom UI and RAG API: python run.py."""
import argparse
import os
from pathlib import Path
import uvicorn


def main():
    parser = argparse.ArgumentParser(description='Start Paper Radio on your computer.')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    os.chdir(Path(__file__).resolve().parent)
    print(f'\nPaper Radio → http://127.0.0.1:{args.port}\nPress Ctrl+C to stop.\n', flush=True)
    uvicorn.run('paper_radio.api:app', host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    main()
