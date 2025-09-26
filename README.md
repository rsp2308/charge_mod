# 🔋 Automatic Charge Sound Player

Play a custom sound automatically when your laptop starts charging!

## � Getting Started (First Time Setup)

### Step 1: Download from GitHub
1. Go to the GitHub repository
2. Click the green **"Code"** button
3. Select **"Download ZIP"**
4. Extract the ZIP file to `d:\charge_mod\` (create the folder if it doesn't exist)

### Step 2: Install Python (if you don't have it)
1. Go to [python.org/downloads](https://python.org/downloads)
2. Download the latest Python version (3.8 or newer)
3. Run the installer
4. **⚠️ IMPORTANT**: Check **"Add Python to PATH"** during installation!
5. Click "Install Now"
6. Test installation:
   - Press `Win + R`, type `cmd`, press Enter
   - Type: `python --version`
   - You should see something like "Python 3.x.x"
   - If you get an error, restart your computer and try again

**Alternative Easy Method:**
- Open Microsoft Store
- Search "Python"
- Install "Python 3.x" (official version)

### Step 3: Verify Files
Make sure you have these files in `d:\charge_mod\`:
- `charge.pyw` - The main script
- `charge.wav` - Your sound file
- `README.md` - This guide

## �📁 What's Included
- `charge.pyw` - Hidden Python script (no console window)
- `charge.wav` - Your custom charge sound
- `README.md` - This guide

## 🚀 Quick Setup (2 Steps)

### Step 1: Test the Script
1. Double-click `charge.pyw` to test the sound
2. You should hear your charge sound play

### Step 2: Set Up Automatic Trigger
1. Press `Win + R`, type `taskschd.msc`, press Enter
2. In Task Scheduler, click **"Create Task..."** in the right panel
3. **General Tab**:
   - Name: `ChargeSound`
   - Description: `Play sound when charging`
   - ☑️ Check "Run with highest privileges"
   - ☑️ Check "Hidden"

4. **Triggers Tab**:
   - Click **"New..."**
   - Begin the task: **"On an event"**
   - Settings:
     - Log: `System`
     - Source: `Microsoft-Windows-Kernel-Power`
     - Event ID: `105`
   - Click **"OK"**

5. **Actions Tab**:
   - Click **"New..."**
   - Action: **"Start a program"**
   - Program: `python` (or `pythonw`)
   - Arguments: `d:\charge_mod\charge.pyw`
   - Start in: `d:\charge_mod`
   - Click **"OK"**

6. **Conditions Tab**:
   - ☑️ Check **"Start the task only if the computer is on AC power"**
   - ☐ Uncheck **"Stop if the computer switches to battery power"**

7. **Settings Tab**:
   - ☑️ Check **"Allow task to be run on demand"**
   - ☑️ Check **"Run task as soon as possible after a scheduled start is missed"**
   - ☐ Uncheck **"Stop the task if it runs longer than"**

8. Click **"OK"** to save the task

## ✅ Done!
Your charge sound will now play automatically when you plug in your charger!

## 🧪 Testing
1. Unplug your laptop charger
2. Wait 5 seconds
3. Plug it back in
4. You should hear the charge sound!

## 🔧 Troubleshooting

**Python not working?**
- Make sure you checked "Add Python to PATH" during installation
- Restart your computer after installing Python
- Try typing `py` instead of `python` in Command Prompt
- If still not working, reinstall Python with PATH option checked

**Script not running when double-clicked?**
- Right-click `charge.pyw` → "Open with" → Choose Python
- Or open Command Prompt in the folder and type: `python charge.pyw`

**Sound not playing?**
- Make sure `charge.wav` exists in the same folder
- Test by double-clicking `charge.pyw`
- Check your default audio device
- Try replacing with a different WAV file

**Task not running automatically?**
- Open Event Viewer (`eventvwr.msc`)
- Go to Windows Logs → System
- Look for Event ID 105 when plugging/unplugging charger
- Verify the task is enabled in Task Scheduler
- Check that "AC power required" is checked in Conditions tab

**Need to remove the task?**
- Open Task Scheduler (`Win + R` → `taskschd.msc`)
- Find "ChargeSound" task
- Right-click → Delete

## 🎵 Customize Sound
Replace `charge.wav` with any WAV file you want. Keep the same filename or update the script path.

---
**That's it! Simple and effective.** 🔋🎵