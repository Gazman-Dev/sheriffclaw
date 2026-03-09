#!/usr/bin/env python3
import sys


def main():
    text = sys.stdin.read()
    summary = (text or "").strip().replace("\n", " ")
    if len(summary) > 160:
        summary = summary[:157] + "..."
    print(summary)


if __name__ == "__main__":
    main()
