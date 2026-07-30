@echo off
rem Launches an interactive PersonalAI chat session (general task).
rem For story/code modes or one-shot messages, use a terminal directly:
rem   conda run -n personalai myai story
rem   conda run -n personalai myai code "explain this regex: ..."
set PYTHONIOENCODING=utf-8
conda run -n personalai --no-capture-output myai chat
pause
