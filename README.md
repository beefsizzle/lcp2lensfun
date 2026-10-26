# Yongnuo YN23mm F1.4R DA DSM (Canon RF) – lens profile for RapidRAW

`yongnuo-yn23mm-rf.xml` is Yongnuo's official Adobe LCP profile converted to Lensfun format.
It covers distortion, chromatic aberration (TCA) and vignetting for f/1.4–f/16.
The RAW and JPEG LCPs Yongnuo ships contain identical data, so one file covers both.

**Status:** the profile loads in RapidRAW 1.6.7 and shows up in the lens list, but it hasn't been
tested on real photos from this lens yet. Feedback welcome: open an issue.

## Install

Copy `yongnuo-yn23mm-rf.xml` into RapidRAW's `lensfun_db` folder, then restart RapidRAW.

| OS | Folder |
|---|---|
| Linux (deb / AUR) | `/usr/lib/RapidRAW/lensfun_db/` (needs sudo) |
| Windows | `C:\Program Files\RapidRAW\lensfun_db\` (or wherever RapidRAW is installed) |
| macOS | `/Applications/RapidRAW.app/Contents/Resources/lensfun_db/` (right-click the app → Show Package Contents) |

```bash
sudo install -m644 yongnuo-yn23mm-rf.xml /usr/lib/RapidRAW/lensfun_db/
```

RapidRAW only reads its bundled `lensfun_db` folder; it has no user profile folder. A RapidRAW update
may remove the file, so you might need to copy it again after updating. AppImage builds are read-only, so
this method doesn't work for them.

In the Lens Correction panel, the lens should be auto-detected. If it isn't, pick **Yongnuo → YN23mm F/1.4R DA DSM**.

## Notes

- The file is standard Lensfun XML and validates against Lensfun's DTD and schema. The same file also works in
  darktable or RawTherapee: put it in `~/.local/share/lensfun/` (darktable) or the Lensfun user folder.
- The conversion is exact: it rescales Adobe's polynomial coefficients, with no curve fitting. One exception is the
  red/blue CA terms. RapidRAW can only apply a constant red/blue scale, so those are averaged over the frame.
  The leftover error there is under half a pixel, even in the corners.
- Lensfun keeps one distortion curve per focal length. That curve comes from the f/8 calibration
  entry; the f/2–f/16 entries are nearly identical. Vignetting is kept per aperture.
- RapidRAW's engine applies about 80–90% of a Lensfun distortion profile at its default Amount of 100
  (true for every lens in its database). If straight lines near the edges still bow slightly,
  set the distortion **Amount to ~115**.

## Converting other LCP files

```bash
python3 lcp2lensfun.py "Some Lens.lcp" --maker Yongnuo --mount "Canon RF" > some-lens.xml
```

Options: `--model` (defaults to the LCP's lens name), `--cropfactor` (defaults to the LCP's value).
Only regular (non-fisheye) LCP profiles are supported.
