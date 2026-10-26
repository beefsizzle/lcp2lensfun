#!/usr/bin/env python3
"""Convert an Adobe Lens Correction Profile (.lcp) into a Lensfun XML entry
that apps with a simplified Lensfun engine (e.g. RapidRAW) can use.

Lensfun's own `lensfun-convert-lcp` emits the "acm" models, which RapidRAW
ignores. This script instead rewrites the Adobe Camera Model into:

  distortion: poly5   (Hugin coords, r = 1 at half the short image side)
  tca:        poly3 with only vr / vb (a pure radial scale, fitted from
              Adobe's red/blue-vs-green model)
  vignetting: pa      (r = 1 at the image corner)

Adobe's model works in coordinates normalised by the focal length in pixels
(fx = FocalLengthX * max(width, height)), so each polynomial term converts
exactly by rescaling: k_n' = k_n * (R / fx) ** (2n), with R being the radius
that the target model calls 1.

Usage: lcp2lensfun.py profile.lcp [--maker X] [--model Y] [--mount Z] > out.xml
"""

import argparse
import math
import sys
import xml.etree.ElementTree as ET

CAM = "{http://ns.adobe.com/photoshop/1.0/camera-profile}"
RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"

STANDARD_STOPS = [1.0, 1.1, 1.2, 1.4, 1.6, 1.8, 2.0, 2.2, 2.5, 2.8, 3.2, 3.5, 4.0, 4.5,
                  5.0, 5.6, 6.3, 7.1, 8.0, 9.0, 10.0, 11.0, 13.0, 14.0, 16.0, 18.0, 20.0, 22.0]


def field(el, name, default=None):
    """Read a field stored either as a child element or as an attribute."""
    if el is None:
        return default
    child = el.find(CAM + name)
    if child is not None and child.text is not None:
        return child.text.strip()
    return el.attrib.get(CAM + name, default)


def submodel(el, name):
    sub = el.find(CAM + name)
    if sub is None:
        return None
    desc = sub.find(RDF + "Description")
    return desc if desc is not None else sub


def params(el, prefix, count=3):
    return [float(field(el, f"{prefix}{i}", 0.0)) for i in range(1, count + 1)]


def apex_to_fnumber(av):
    n = 2 ** (av / 2)
    return min(STANDARD_STOPS, key=lambda s: abs(s - n))


def read_entries(path):
    root = ET.parse(path).getroot()
    entries = []
    for li in root.iter(RDF + "li"):
        if field(li, "FocalLength") is None:
            continue
        persp = submodel(li, "PerspectiveModel")
        if persp is None:
            print(f"warning: skipping non-perspective entry in {path}", file=sys.stderr)
            continue
        width = float(field(li, "ImageWidth"))
        height = float(field(li, "ImageLength"))
        entries.append({
            "li": li,
            "persp": persp,
            "focal": float(field(li, "FocalLength")),
            "fnumber": apex_to_fnumber(float(field(li, "ApertureValue"))),
            "distance": float(field(li, "FocusDistance", 1000)),
            "width": width,
            "height": height,
            "dmax": max(width, height),
        })
    if not entries:
        sys.exit(f"error: no usable calibration entries in {path}")
    return entries


def fmt(x):
    return f"{x:.7g}"


def distortion_element(e):
    p = e["persp"]
    fx = float(field(p, "FocalLengthX")) * e["dmax"]
    half_short = min(e["width"], e["height"]) / 2
    s = (half_short / fx) ** 2
    k1, k2, k3 = params(p, "RadialDistortParam")
    attrs = {"model": "poly5", "focal": fmt(e["focal"]), "k1": fmt(k1 * s), "k2": fmt(k2 * s * s)}
    if k3:
        print("warning: dropping RadialDistortParam3 (poly5 has no k3 term)", file=sys.stderr)
    return ET.Element("distortion", attrs)


def fit_linear_tca(chroma, fx, r_max, samples=400):
    """Least-squares constant scale matching alpha0*(1 + a1 r^2 + a2 r^4 + a3 r^6),
    weighted by image area (r dr) over the radius range the image covers."""
    a0 = float(field(chroma, "ScaleFactor", 1.0))
    a1, a2, a3 = params(chroma, "RadialDistortParam")
    num = den = 0.0
    for i in range(1, samples + 1):
        r = (i - 0.5) / samples * r_max / fx
        w = r
        scale = a0 * (1 + a1 * r**2 + a2 * r**4 + a3 * r**6)
        num += w * scale
        den += w
    return num / den


def tca_element(e):
    p = e["persp"]
    green = submodel(p, "ChromaticGreenModel")
    if green is None:
        green = p
    red = submodel(p, "ChromaticRedGreenModel")
    blue = submodel(p, "ChromaticBlueGreenModel")
    if red is None or blue is None:
        return None
    fx = float(field(green, "FocalLengthX")) * e["dmax"]
    half_diag = math.hypot(e["width"], e["height"]) / 2
    vr = fit_linear_tca(red, fx, half_diag)
    vb = fit_linear_tca(blue, fx, half_diag)
    # poly3 with only the v terms is a pure radial scale (same as "linear"), and
    # vr/vb is the form RapidRAW reads.
    return ET.Element("tca", {"model": "poly3", "focal": fmt(e["focal"]), "vr": fmt(vr), "vb": fmt(vb)})


def vignetting_element(e):
    vig = submodel(e["persp"], "VignetteModel")
    if vig is None:
        return None
    fx = float(field(vig, "FocalLengthX")) * e["dmax"]
    half_diag = math.hypot(e["width"], e["height"]) / 2
    s = (half_diag / fx) ** 2
    a1, a2, a3 = params(vig, "VignetteModelParam")
    return ET.Element("vignetting", {
        "model": "pa", "focal": fmt(e["focal"]), "aperture": fmt(e["fnumber"]),
        "distance": fmt(e["distance"]),
        "k1": fmt(a1 * s), "k2": fmt(a2 * s**2), "k3": fmt(a3 * s**3)})


def reference_entry(entries):
    """Lensfun stores one distortion/TCA set per focal length; like
    lensfun-convert-lcp, take the entry closest to f/8 (sharpest, most stable fit)."""
    return min(entries, key=lambda e: (abs(e["fnumber"] - 8), -e["distance"]))


def build(entries, args):
    first = entries[0]["li"]
    lens = ET.Element("lens")
    ET.SubElement(lens, "maker").text = args.maker
    ET.SubElement(lens, "model").text = args.model or field(first, "Lens") or field(first, "LensPrettyName")
    ET.SubElement(lens, "mount").text = args.mount
    crop = args.cropfactor or float(field(first, "SensorFormatFactor", 1.0))
    ET.SubElement(lens, "cropfactor").text = fmt(round(crop, 3))
    cal = ET.SubElement(lens, "calibration")

    by_focal = {}
    for e in entries:
        by_focal.setdefault(e["focal"], []).append(e)

    for focal in sorted(by_focal):
        ref = reference_entry(by_focal[focal])
        cal.append(ET.Comment(f" distortion/TCA from the f/{fmt(ref['fnumber'])} calibration entry "))
        cal.append(distortion_element(ref))
        tca = tca_element(ref)
        if tca is not None:
            cal.append(tca)
    for e in sorted(entries, key=lambda e: (e["focal"], e["fnumber"], e["distance"])):
        vig = vignetting_element(e)
        if vig is not None:
            cal.append(vig)
    return lens


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lcp")
    ap.add_argument("--maker", required=True)
    ap.add_argument("--model", help="defaults to the LCP's Lens field")
    ap.add_argument("--mount", required=True)
    ap.add_argument("--cropfactor", type=float, help="defaults to the LCP's SensorFormatFactor")
    ap.add_argument("--note", help="XML comment placed above the lens entry")
    args = ap.parse_args()

    lens = build(read_entries(args.lcp), args)
    db = ET.Element("lensdatabase", {"version": "2"})
    if args.note:
        db.append(ET.Comment(f" {args.note} "))
    db.append(lens)
    ET.indent(db, space="    ")
    sys.stdout.write('<?xml version="1.0" encoding="utf-8"?>\n')
    sys.stdout.write(ET.tostring(db, encoding="unicode"))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
