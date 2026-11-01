"""Точка входа для хостингов, которые запускают один .py файл: python main.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from bot.main import main  # noqa: E402

if __name__ == "__main__":
    main()
