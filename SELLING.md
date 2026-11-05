# Selling checklist

Work through this list in order. Items marked **(you)** need a decision, an account or a payment that only you can make. The code side is done.

## 1. Name and brand (you)
- [ ] **Pick a new product name.** Texas Instruments already uses "MathDraw" for a gesture-drawing feature in TI-Nspire, in the same field (math education). Selling under that name invites a trademark dispute.
- [ ] Search the name in the trademark databases where you'll sell (USPTO in the US, EUIPO in the EU, and so on), in app stores, and as a domain name.
- [ ] Edit **`mathdraw/branding.py`**: `APP_NAME`, `PUBLISHER`, `WEBSITE`, `BUY_URL`, `SUPPORT_EMAIL`, `PRODUCT_CODE`, `TRIAL_DAYS`. Every window title, dialog and installer field reads from this file.
- [ ] Optional: replace `mathdraw/assets/icon.png` and `icon.ico` with your own artwork. `packaging/make_icon.py` regenerates the default icon.

## 2. Business basics (you)
- [ ] Decide how you'll sell: as a sole proprietor or through an LLC or company. Ask an accountant about income tax.
- [ ] Use a **merchant-of-record** storefront, such as Lemon Squeezy, Paddle or Gumroad. It collects and pays sales tax and VAT worldwide for you, which is the hard part of selling software internationally.
- [ ] Write a refund policy. Many software sellers offer 14–30 days.

## 3. Licence keys (one-time setup)
```
python tools/make_signing_keys.py
```
- This creates `tools/PRIVATE_signing_key.pem`. **Back it up in two safe places** (a password manager and an encrypted drive). If you lose it, you can't issue keys that already-sold builds accept. Never share it, ship it or commit it to git.
- It also writes `mathdraw/license_pubkey.txt`, which is bundled into the app. From then on, builds give new users a **14-day trial** and then ask for a key.
- To issue a key for one buyer: `python tools/issue_license.py "Buyer Name" buyer@email`. E-mail them the printed `MD1-…` key. A record is appended to `tools/issued_licenses.csv`.
- To issue a batch: `python tools/issue_license.py --batch 200` prints 200 generic keys. Use this if your storefront can deliver keys from a list you upload; otherwise send keys from each order notification.
- Keys are checked offline with an Ed25519 signature, so they can't be forged without your private key. Like any offline scheme, a determined person could patch the program to skip the check. This keeps honest people honest, which is the realistic goal for indie software.

## 4. Build the installer (Windows)
1. Install **Python 3.12 (64-bit)** from python.org and **Inno Setup 6** from jrsoftware.org.
2. Double-click **`build.bat`**. It does the following:
   - creates a clean build environment
   - downloads the hand-tracking model so it ships inside the app (buyers' copies never download anything)
   - runs the 46 automated tests
   - collects third-party licences into `licenses/`
   - builds the app with PyInstaller
   - runs the built app's `--selftest`
   - compiles `dist\installer\<Name>-Setup-<version>.exe`
3. The installer installs per-user without an admin prompt. It adds Start menu and optional desktop shortcuts, shows the EULA, and includes an uninstaller.
4. **Keep the `AppId` GUID in `packaging/installer.iss` forever.** Windows uses it to recognise that a new version upgrades the old one.

## 5. Code signing (strongly recommended) (you)
An unsigned installer triggers a strong Windows SmartScreen warning ("Windows protected your PC"), which costs sales. According to Microsoft's current guidance, your options are:
- **Azure Artifact Signing** (formerly Trusted Signing): about $9.99/month. It's available to organisations in the US, Canada, EU and UK, and to individual developers in the US and Canada.
- **OV certificate** from DigiCert, Sectigo and others: about $150–300/year, available worldwide. The key must be stored on a hardware token or HSM.
- **EV certificates** no longer bypass SmartScreen instantly (Microsoft removed that in 2024). With any signing method, the warning fades as your signed releases build reputation.
- Alternative: publish through the **Microsoft Store** as MSIX. Microsoft signs the package for you, so users see no SmartScreen warning. This requires repackaging.

Once you have a signing setup, uncomment the `signtool` line in `build.bat` and the `SignTool=` lines in `packaging/installer.iss`.

## 6. Legal (you, with a lawyer)
- [ ] Complete and have reviewed: `EULA.txt`, `PRIVACY.txt` (both are templates with [BRACKETED] blanks), and your refund policy.
- [ ] Open-source compliance, already set up:
  - Qt/PySide6 (LGPLv3) is shipped unmodified as separate DLLs. The build is "one-folder" for this reason; don't switch to one-file.
  - The notices and every package's licence text ship with the app.
  - The EULA carves out the rights the LGPL requires.
  
  Keep it that way, and send the Qt source (or a link to it) if anyone asks.
- [ ] Don't promise exact results in your marketing. The app estimates equations from drawings and says so (EULA §7).

## 7. Test before launch
- [ ] Install on a **clean Windows 10 and Windows 11 machine or VM** that has never had Python installed. Then check:
  - the first-run welcome screen
  - the trial countdown in the title bar
  - camera permission (Settings ▸ Privacy ▸ Camera ▸ "Let desktop apps access your camera")
  - drawing in every draw mode
  - entering a licence key
  - expiry, by testing with `TRIAL_DAYS = 0` in a private test build
  - uninstalling and reinstalling (the licence should survive)
- [ ] Work through every row of `TESTING.md` with a real webcam.
- [ ] Try two or three different webcams and lighting conditions.

## 8. Releasing updates
- Bump `VERSION` in `branding.py`, run `build.bat`, then publish the new installer. Settings and licences carry over automatically.
- Logs are in `%LOCALAPPDATA%\<APP_ID>\logs\`, and Help ▸ Open log folder opens them. Ask users to attach a log file to support e-mails.

## 9. Know the product's limits (put them on your sales page)
- Windows 10/11, 64-bit, with a webcam. The installer is fairly large (expect a few hundred MB installed), because it bundles a complete math and hand-tracking stack.
- Each analysis takes a few seconds, adjustable in Settings ▸ Analysis.
- Recognition is good for common Calculus I/II curves. With heavy hand shake, the app reports "uncertain" and lists alternatives rather than guessing silently.
