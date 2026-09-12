# 07: Localization (i18n) Engine and Standalone 1-Click Desktop Packaging

**What to build:** A centralized multi-language translation dictionary supporting German and English, with a clean header dropdown selector and local preference persistence. In addition, double-clickable `Start_Item_Researcher.bat` launcher and PyInstaller configuration to package the application as a standalone executable.

**Blocked by:** 05 (Single-Item Re-Appraisal), 06 (eBay Marketplace Confirmation Modal)

**Status:** ready-for-agent

- [ ] Centralized client-side localization dictionary supporting German (`de`) and English (`en`)
- [ ] Header language selector updating all UI labels dynamically and persisting selection
- [ ] Windows double-clickable `Start_Item_Researcher.bat` starting server and opening browser
- [ ] PyInstaller build script / configuration for zero-setup `.exe` distribution
