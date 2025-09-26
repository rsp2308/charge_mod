import winsound
import os

# Simple charge sound player
sound_file = r"d:\charge_mod\charge.wav"

if os.path.exists(sound_file):
    print("Playing charge sound...")
    winsound.PlaySound(sound_file, winsound.SND_FILENAME)
    print("Done!")
else:
    print("Sound file not found!")
    winsound.Beep(800, 1000)  # Backup beep
