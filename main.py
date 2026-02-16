import os
import runpy
import sys

print("Python runner is up!")

# Add the directory containing the 'bot' package to sys.path
bot_path = os.path.join(os.path.dirname(__file__), "telegram-casino-bot")
sys.path.insert(0, bot_path)

# Set configuration path if not already set
if "CONFIG_FILE_PATH" not in os.environ:
    config_path = os.path.join(bot_path, "settings.toml")
    os.environ["CONFIG_FILE_PATH"] = config_path
    print(f"Config file set to: {config_path}")

# Run the bot
try:
    print(f"Starting bot from {bot_path}...")
    runpy.run_module("bot", run_name="__main__")
except Exception as e:
    print(f"Error running bot: {e}")
    sys.exit(1)
