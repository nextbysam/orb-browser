"""
Vision agent: give a browser a task in natural language.

The agent takes screenshots, sends them to a vision LLM,
and executes actions (click, type, scroll, navigate) until done.

Usage:
    ORB_API_KEY=orb_... python examples/vision_task.py
"""
import os
from orb_browser import OrbBrowser

orb = OrbBrowser(api_key=os.environ["ORB_API_KEY"])
orb.deploy()

# The agent navigates to the page, screenshots it, and uses
# Gemini Flash to understand what's on screen.
# No LLM key needed — the built-in key is used automatically.
result = orb.task(
    "Read this page and tell me what it says",
    model="google/gemini-2.0-flash-001",
)
print(f"Result: {result}")

# Try a more complex task
result = orb.task(
    "Go to news.ycombinator.com and tell me the top 3 stories",
    model="google/gemini-2.0-flash-001",
)
print(f"Top stories: {result}")

orb.sleep()  # $0 while sleeping
print(f"Browser sleeping. Wake later with: orb.wake()")
