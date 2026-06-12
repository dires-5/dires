# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║       PDF EXTRACTOR — Fayda Digital ID Card                  ║
║                                                              ║
║  Extracts from uploaded Fayda PDF:                           ║
║   • All text fields (name, DOB, FCN, phone, address...)      ║
║   • Portrait photo (img-003.jpg — top-left above FCN)        ║
║   • QR code image  (img-004.jpg — left-middle below phone)   ║
║   • Decodes QR code data                                     ║
║   • Builds api_data dict compatible with merge_to_template() ║
╚══════════════════════════════════════════════════════════════╝
"""

import io
import re
import os
import base64
import tempfile
import subprocess
from PIL import Image

# ── QR DECODE  ────────────────────────────────────────────────────────────────
def _decode_qr(img: Image.Image) -> str:
    """Try multiple QR decode strategies. Returns decoded string or ''."""

    # Strategy 1: pyzbar (fastest, most reliable)
    try:
        from pyzbar.pyzbar import decode as pyzbar_decode
        results = pyzbar_decode(img)
        if results:
            return results[0].data.decode("utf-8", errors="ignore")
    except ImportError:
        pass
    except Exception:
        pass

    # Strategy 2: opencv + wechat_qrcode detector
    try:
        import cv2
        import numpy as np
        arr = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2GRAY)
        detector = cv2.QRCodeDetector()
        data, _, _ = detector.detectAndDecode(arr)
        if data:
            return data
    except Exception:
        pass

    # Strategy 3: zxing-cpp if installed
    try:
        import zxingcpp
        import numpy as np
        arr = np.array(img.convert("RGB"))
        results = zxingcpp.read_barcodes(arr)
        if results:
            return results[0].text
    except ImportError:
        pass
    except Exception:
        pass

    return ""


# ── IMAGE EXTRACTION FROM PDF  ────────────────────────────────────────────────
def _extract_images_pymupdf(pdf_bytes: bytes) -> list:
    """
    Fallback image extractor using PyMuPDF (fitz) — pure Python, no system deps.
    Returns list of PIL.Image objects sorted by xref (stable order matching
    pdfimages -list output).

    Image order in Fayda PDF (confirmed):
      index 0: watermark mask (gray, 361×350)
      index 1: star logo      (rgb,  361×350)
      index 2: mask           (gray, 361×350)
      index 3: PORTRAIT PHOTO (rgb,  413×531)  ← PHOTO
      index 4: QR CODE        (gray, 250×250)  ← QR
      index 5: card front     (rgb, 1968×3150)
      index 6: card back      (rgb, 1968×3150)
    """
    import fitz  # PyMuPDF
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []
    seen_xrefs = set()
    for page in doc:
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            try:
                base_img = doc.extract_image(xref)
                img_bytes = base_img["image"]
                img = Image.open(io.BytesIO(img_bytes)).copy()
                images.append((xref, img))
            except Exception:
                pass
    # Sort by xref so order is stable and matches pdfimages numbering
    images.sort(key=lambda x: x[0])
    return [img for _, img in images]


def _extract_images_from_pdf(pdf_bytes: bytes) -> list:
    """
    Extract all embedded images from PDF bytes.
    Tries pdfimages (poppler) first; falls back to PyMuPDF if unavailable.
    Returns list of PIL.Image objects sorted by object ID (stable order).

    Image order in Fayda PDF (confirmed from pdfimages -list output):
      index 0: img-000 — watermark mask (gray, tiny)
      index 1: img-001 — star logo (index/png, ~134 KB)
      index 2: img-002 — mask (gray)
      index 3: img-003 — PORTRAIT PHOTO (rgb jpeg, 413×531, 28 KB)  ← PHOTO
      index 4: img-004 — QR CODE      (gray jpeg, 250×250, 11 KB)   ← QR
      index 5: img-005 — card front   (rgb jpeg, large)
      index 6: img-006 — card back    (rgb jpeg, large)
    """
    # ── Strategy 1: pdfimages (poppler) ──────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = os.path.join(tmpdir, "input.pdf")
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)

        pdfimages_ok = False
        try:
            proc = subprocess.run(
                ["pdfimages", "-all", pdf_path, os.path.join(tmpdir, "img")],
                capture_output=True, timeout=30
            )
            pdfimages_ok = proc.returncode == 0
        except (FileNotFoundError, Exception):
            pdfimages_ok = False

        if pdfimages_ok:
            images = []
            for fname in sorted(os.listdir(tmpdir)):
                if fname == "input.pdf":
                    continue
                fpath = os.path.join(tmpdir, fname)
                try:
                    img = Image.open(fpath).copy()
                    images.append(img)
                except Exception:
                    pass
            if images:
                return images

    # ── Strategy 2: PyMuPDF fallback (pure Python, works on all platforms) ───
    try:
        return _extract_images_pymupdf(pdf_bytes)
    except ImportError:
        pass
    except Exception:
        pass

    return []


# ── TEXT EXTRACTION FROM PDF  ─────────────────────────────────────────────────
def _extract_text_pymupdf(pdf_bytes: bytes) -> str:
    """
    Pure-Python text extraction fallback using PyMuPDF, used when the
    `pdftotext` binary (poppler-utils) is not available on the host
    (e.g. some PaaS deployments like Render don't install it).

    Reconstructs a `pdftotext -layout`-like output by grouping words into
    rows based on their vertical position, then ordering words within each
    row left-to-right and joining with spacing proportional to the
    horizontal gap. This preserves the two-column table structure that
    _parse_fayda_text's positional/regex logic depends on.
    """
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        out_lines = []
        for page in doc:
            words = page.get_text("words")  # (x0, y0, x1, y1, text, block, line, word_no)
            if not words:
                continue
            # Group words into rows by y0, tolerant of small jitter
            words_sorted = sorted(words, key=lambda w: (round(w[1] / 3) * 3, w[0]))
            rows = []
            current_row = []
            current_y = None
            for w in words_sorted:
                y0 = w[1]
                if current_y is None or abs(y0 - current_y) <= 3:
                    current_row.append(w)
                    current_y = y0 if current_y is None else current_y
                else:
                    rows.append(current_row)
                    current_row = [w]
                    current_y = y0
            if current_row:
                rows.append(current_row)

            # Render each row: sort by x, insert spacing scaled by gap size
            for row in rows:
                row = sorted(row, key=lambda w: w[0])
                pieces = []
                prev_x1 = None
                for w in row:
                    x0, x1, text = w[0], w[2], w[4]
                    if prev_x1 is not None:
                        gap = x0 - prev_x1
                        # ~1 space per 3pt gap, min 1 space, cap to avoid huge lines
                        n_spaces = max(1, min(int(gap / 3), 60))
                    else:
                        n_spaces = 0
                    pieces.append(" " * n_spaces + text)
                    prev_x1 = x1
                out_lines.append("".join(pieces))
        return "\n".join(out_lines)
    except Exception:
        return ""


def _extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract all text from PDF using pdftotext with layout preservation.

    Falls back to PyMuPDF-based extraction if `pdftotext` (poppler-utils)
    is not installed on the host.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = os.path.join(tmpdir, "input.pdf")
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)
        try:
            result = subprocess.run(
                ["pdftotext", "-layout", pdf_path, "-"],
                capture_output=True, timeout=30
            )
            if result.returncode == 0:
                text = result.stdout.decode("utf-8", errors="ignore")
                if text.strip():
                    return text
        except (FileNotFoundError, Exception):
            pass

    # Fallback: pure-Python extraction (works even without poppler-utils)
    return _extract_text_pymupdf(pdf_bytes)


# ── PARSE FAYDA TEXT  ─────────────────────────────────────────────────────────
def _parse_fayda_text(text: str) -> dict:
    """
    Parse extracted PDF text into structured fields.
    Handles both English and Amharic text blocks from the Fayda layout.
    """
    info = {
        "full_name_eng": "",
        "full_name_amh": "",
        "dob_gregorian": "",     # e.g. 05/03/1993
        "dob_ethiopian": "",     # e.g. 2000/11/14
        "sex_eng": "",
        "sex_amh": "",
        "nationality_eng": "",
        "nationality_amh": "",
        "phone": "",
        "region_eng": "",
        "region_amh": "",
        "subcity_eng": "",
        "subcity_amh": "",
        "woreda_eng": "",
        "woreda_amh": "",
        "fcn": "",
        "fin": "",
        "expiry": "",
    }

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    full_text = "\n".join(lines)

    # ── FCN (16-digit card number)  ───────────────────────────────────────────
    # Format: "5640 5396 8043 1745" or "5640539680431745"
    fcn_match = re.search(r'(\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4})', full_text)
    if fcn_match:
        info["fcn"] = re.sub(r'[\s\-]', '', fcn_match.group(1))

    # ── Phone  ────────────────────────────────────────────────────────────────
    phone_match = re.search(r'(09\d{8}|07\d{8}|\+2519\d{8})', full_text)
    if phone_match:
        info["phone"] = phone_match.group(1)

    # ── DOB: look for two date patterns near each other ───────────────────────
    # Gregorian: DD/MM/YYYY  or  DD/Mon/YYYY
    # Ethiopian: YYYY/MM/DD
    # In PDF text they appear as e.g. "05/03/1993\n2000/11/14"
    greg_match = re.search(r'(\d{2}/\d{2}/\d{4})', full_text)
    if greg_match:
        info["dob_gregorian"] = greg_match.group(1)

    eth_match = re.search(r'(\d{4}/\d{2}/\d{2})', full_text)
    if eth_match:
        info["dob_ethiopian"] = eth_match.group(1)

    # ── Names: look for Amharic + English name near "ሙሉ ስም" header ───────────
    # Name extraction: scan lines around "ሙሉ ስም / First, Middle, Surname"
    for i, line in enumerate(lines):
        if "ሙሉ ስም" in line or "First, Middle, Surname" in line:
            candidates = [l.strip() for l in lines[i+1:i+6] if l.strip()]
            for c in candidates:
                has_amh = bool(re.search(r'[\u1200-\u137F]', c))
                # The English name appears after "FCN: XXXX XXXX..." on the same line
                if has_amh and not info["full_name_amh"]:
                    info["full_name_amh"] = c
                elif "FCN" in c and not info["full_name_eng"]:
                    # Extract name after the FCN number
                    m_fcn = re.search(r'FCN:[\s\d]+\s{2,}([A-Z][a-zA-Z ]+)$', c)
                    if m_fcn:
                        info["full_name_eng"] = m_fcn.group(1).strip()
                elif re.match(r'^[A-Z][a-z]', c) and not info["full_name_eng"] and "FCN" not in c:
                    info["full_name_eng"] = c
            break

    # ── Sex  ─────────────────────────────────────────────────────────────────
    if re.search(r'\bMale\b', full_text, re.IGNORECASE):
        info["sex_eng"] = "Male"
    elif re.search(r'\bFemale\b', full_text, re.IGNORECASE):
        info["sex_eng"] = "Female"
    amh_male = re.search(r'ወንድ', full_text)
    if amh_male:
        info["sex_amh"] = "ወንድ"
    amh_female = re.search(r'ሴት', full_text)
    if amh_female:
        info["sex_amh"] = "ሴት"

    # ── Nationality  ──────────────────────────────────────────────────────────
    if re.search(r'\bEthiopian\b', full_text):
        info["nationality_eng"] = "Ethiopian"
    amh_nat = re.search(r'ኢትዮጵያዊ[ት]?', full_text)
    if amh_nat:
        info["nationality_amh"] = amh_nat.group(0)

    # ── Region  ───────────────────────────────────────────────────────────────
    regions_eng = ["Addis Ababa", "Oromia", "Amhara", "Tigray", "Somali",
                   "Afar", "SNNP", "Sidama", "South West Ethiopia", "South Ethiopia",
                   "Benishangul Gumuz", "Benishangul-Gumuz", "Gambela", "Harari",
                   "Dire Dawa", "Central Ethiopia"]
    region_match = re.search(r'(' + '|'.join(re.escape(r) for r in regions_eng) + r')', full_text, re.IGNORECASE)
    if region_match:
        info["region_eng"] = region_match.group(1)

    regions_amh = ["አዲስ አበባ", "ኦሮሚያ", "አማራ", "ትግራይ", "ሶማሌ", "አፋር",
                   "ደቡብ", "ቤንሻንጉል ጉምዝ", "ቤንሻንጉል", "ጋምቤላ", "ሐረሪ",
                   "ድሬዳዋ", "ድሬ ዳዋ", "መካከለኛው ኢትዮ"]
    amh_region = re.search(r'(' + '|'.join(re.escape(r) for r in regions_amh) + r')', full_text)
    if amh_region:
        info["region_amh"] = amh_region.group(1)

    # ── Subcity / Zone  ───────────────────────────────────────────────────────
    # pdftotext -layout merges the left and right columns of a row into one
    # line separated by a large run of spaces, e.g.:
    #   "ፆታ / SEX                                ክፍለ ከተማ / ዞን / Subcity / zone"
    #   "ሴት                                      ምስራቅ ሀረርጌ"
    #   "Female                                  East Harerge"
    # So we must take only the RIGHT-hand column (after the big gap).
    def _right_column(line: str) -> str:
        parts = [p for p in re.split(r'\s{2,}', line.strip()) if p.strip()]
        if not parts:
            return ""
        if len(parts) == 1:
            return parts[0].strip()
        # Two-column rows: take the second segment (the right column).
        # Extra trailing segments can appear from overlapping text boxes
        # (e.g. disclaimer text bleeding into the same row) and should
        # be ignored.
        return parts[1].strip()

    for i, line in enumerate(lines):
        if "Subcity" in line or "ዞን" in line:
            candidates = [_right_column(l) for l in lines[i+1:i+4] if l.strip()]
            for c in candidates:
                if not c:
                    continue
                has_amh = bool(re.search(r'[\u1200-\u137F]', c))
                if has_amh and not info["subcity_amh"]:
                    info["subcity_amh"] = c
                elif not has_amh and not info["subcity_eng"] and re.match(r'^[A-Za-z]', c):
                    info["subcity_eng"] = c.strip()
            break

    # ── Woreda  ───────────────────────────────────────────────────────────────
    # Same positional approach following the "Woreda" header line.
    woreda_match = re.search(r'Woreda\s+(\d+)', full_text, re.IGNORECASE)
    if woreda_match:
        info["woreda_eng"] = f"Woreda {woreda_match.group(1)}"
    amh_woreda = re.search(r'ወረዳ\s+(\d+)', full_text)
    if amh_woreda:
        info["woreda_amh"] = f"ወረዳ {amh_woreda.group(1)}"

    if not info["woreda_eng"] and not info["woreda_amh"]:
        for i, line in enumerate(lines):
            if re.search(r'Woreda\s*$', line, re.IGNORECASE) or "ወረዳ" in line:
                candidates = [_right_column(l) for l in lines[i+1:i+4] if l.strip()]
                for c in candidates:
                    if not c:
                        continue
                    has_amh = bool(re.search(r'[\u1200-\u137F]', c))
                    if has_amh and not info["woreda_amh"]:
                        info["woreda_amh"] = c
                    elif not has_amh and not info["woreda_eng"] and re.match(r'^[A-Za-z]', c):
                        info["woreda_eng"] = c.strip()
                break

    # ── FIN — extracted via OCR on the card back image (img[6])  ────────────
    # FIN is NOT in the text layer — it's rendered on the card back image
    # "ፋይዳ ልዩ ቁጥር | FIN 9361 9631 5294"  at approximately y=2000-2200 on a 3150px card
    # We pass it through from the caller when images are provided
    pass  # FIN is populated by _extract_fin_from_card_back() if called separately

    # ── FIN (12-digit, if present in text layer)  ────────────────────────────
    # Usually NOT present in the text layer (it's rendered as an image on
    # the card back), but check anyway as a free fallback.
    # Handles: "FIN 6586 9150 6375", "FIN: 658691506375", "FIN6586 9150 6375"
    fin_match = re.search(r'\bFIN\b[\s:]*([\d][\d\s]{10,16}[\d])', full_text, re.IGNORECASE)
    if fin_match:
        digits = re.sub(r'\s', '', fin_match.group(1))
        if 10 <= len(digits) <= 16:
            info["fin"] = digits[:12]

    return info


# ── BUILD API_DATA DICT  ──────────────────────────────────────────────────────
def _build_api_data(parsed: dict, photo_b64: str, qr_data: str, qr_crop_b64: str = "") -> dict:
    """
    Build the api_data dict that merge_to_template() expects,
    from the parsed text fields + photo + QR content.
    """
    # Convert DOB to ISO format (YYYY-MM-DD) for format_dob_dual()
    dob = parsed.get("dob_gregorian", "")
    if dob:
        parts = dob.split("/")
        if len(parts) == 3:
            # Input: DD/MM/YYYY → YYYY-MM-DD
            dob = f"{parts[2]}-{parts[1]}-{parts[0]}"

    api_data = {
        "fullName": {
            "eng": parsed.get("full_name_eng", ""),
            "amh": parsed.get("full_name_amh", ""),
        },
        "dateOfBirth": dob,
        "gender": {
            "eng": parsed.get("sex_eng", ""),
            "amh": parsed.get("sex_amh", ""),
        },
        "phone": parsed.get("phone", ""),
        "uin": parsed.get("fcn", ""),
        "uniqueId": parsed.get("fcn", ""),
        "region": {
            "eng": parsed.get("region_eng", ""),
            "amh": parsed.get("region_amh", ""),
        },
        "zone": {
            "eng": parsed.get("subcity_eng", ""),
            "amh": parsed.get("subcity_amh", ""),
        },
        "woreda": {
            "eng": parsed.get("woreda_eng", ""),
            "amh": parsed.get("woreda_amh", ""),
        },
        "residenceStatus": {
            "eng": parsed.get("nationality_eng", "Ethiopian"),
            "amh": parsed.get("nationality_amh", "ኢትዮጵያዊ"),
        },
        "photo": photo_b64,
        "fin": parsed.get("fin", ""),
        # Pass QR JWT/sign data so the generated QR matches original
        "qr_jwt": qr_data,
        "qr_sign": "",
        # Coordinate-cropped QR image from card back (base64 JPEG),
        # for direct placement on the template without re-decoding
        "qr_crop": qr_crop_b64,
    }
    return api_data


def _crop_qr_from_card_back(card_back_img: "Image.Image") -> "Image.Image":
    """
    Crop the QR code region from the card-back image by fixed coordinates
    (no decoding — just crop the area for direct placement on the template).

    On the 1968x3150 card-back image, the QR sits at:
      x: 8% .. 92% of width   (skips left card border)
      y: 12.5% .. 64.8%       (skips teal header at top, stops above FIN line)

    Pixel-scanned exact bounds on reference card:
      QR top  ≈ y=409  (13.0%)
      QR bottom ≈ y=2041 (64.8%)
      QR left  ≈ x=199  (10.1%)
      QR right ≈ x=1760 (89.4%)
    Small extra padding added so finder squares are never clipped.
    """
    w, h = card_back_img.size
    box = (int(w * 0.08), int(h * 0.10),  int(w * 0.92), int(h * 0.60))
    return card_back_img.crop(box)


def _extract_fin_from_card_back(card_back_img: "Image.Image", pdf_bytes: bytes = b"") -> str:
    """
    Extract the 12-digit FIN number from the Fayda ID card PDF.

    The FIN ("ፋይዳ ልዩ ቁጥር | FIN XXXX XXXX XXXX") is printed as plain text
    on the card-back panel, to the RIGHT of the Phone Number field, just
    below the large QR code.  It is NOT in the PDF text layer — it is
    rendered into the page raster.

    Confirmed layout (full-page render at 6x, ~3572×5052 px):
      x: 55% – 100% of full page width  (right panel only)
      y: 57.0% – 59.6% of full page height

    Three layers, first success wins:
      Layer 1 — fitz PDF text layer  (free; rarely works but worth trying)
      Layer 2 — fitz 6× page render → precise crop → pytesseract  (BEST)
      Layer 3 — card-back embedded JPEG → same crop logic → pytesseract
    """
    import re as _re
    from PIL import Image as _PILImage, ImageFilter as _ImageFilter

    # FIN is 12 digits in groups of 4: "FIN 9361 9631 5294"
    fin_pat = _re.compile(
        r'FIN\s*(\d{4})\s*(\d{4})\s*(\d{4})',
        _re.IGNORECASE
    )

    def _parse(text: str) -> str:
        """Return 12-digit FIN string or '' from OCR text."""
        m = fin_pat.search(text)
        if m:
            digits = m.group(1) + m.group(2) + m.group(3)
            if len(digits) == 12 and digits.isdigit():
                return digits
        return ""

    def _ocr_strip(strip_img: "_PILImage.Image") -> str:
        """Run pytesseract on an already-cropped strip; return raw string."""
        try:
            import pytesseract as _tess
            gray = strip_img.convert("L").filter(_ImageFilter.SHARPEN)
            # psm 11 = sparse text (best for a single labelled value in a noisy background)
            # psm 3  = auto — good fallback
            for psm in [11, 3, 6]:
                text = _tess.image_to_string(
                    gray,
                    config=f'--psm {psm} -c tessedit_char_whitelist="FIN 0123456789"'
                )
                if _parse(text):
                    return text
            return ""
        except ImportError:
            return ""   # tesseract binary not installed
        except Exception as e:
            print(f"[fin] OCR error: {e}")
            return ""

    # ── Layer 1: PDF text layer (instant, usually empty for FIN) ─────────────
    if pdf_bytes:
        try:
            import fitz as _fitz
            doc = _fitz.open(stream=pdf_bytes, filetype="pdf")
            for page in doc:
                result = _parse(page.get_text())
                if result:
                    print(f"[fin] Layer-1 (text layer) SUCCESS: {result}")
                    return result
        except Exception as e:
            print(f"[fin] Layer-1 error: {e}")

    # ── Layer 2: fitz 6× page render → precise FIN crop → pytesseract ────────
    #
    # FIN location on the full-page render (confirmed on multiple real IDs):
    #   x: 55% – 100% of page width   (right half = card-back panel)
    #   y: 57.0% – 59.6% of page height
    #
    # Widening y by ±1.5% handles minor layout variations across ID batches.
    if pdf_bytes:
        try:
            import fitz as _fitz
            doc = _fitz.open(stream=pdf_bytes, filetype="pdf")
            page = doc[-1]  # last page = card back (doc[0] = card front)
            mat = _fitz.Matrix(6.0, 6.0)   # ~432 DPI — sharp enough for OCR
            pix = page.get_pixmap(matrix=mat)
            img = _PILImage.frombytes("RGB", [pix.width, pix.height], pix.samples)
            pw, ph = img.size
            for y0, y1 in [(0.570, 0.596), (0.555, 0.610), (0.540, 0.625)]:
                strip = img.crop((int(pw * 0.55), int(ph * y0), pw, int(ph * y1)))
                ocr_text = _ocr_strip(strip)
                result = _parse(ocr_text)
                if result:
                    print(f"[fin] Layer-2 (6x render y={y0:.3f}-{y1:.3f}) SUCCESS: {result}")
                    return result
        except ImportError:
            pass   # pytesseract / fitz not available
        except Exception as e:
            print(f"[fin] Layer-2 error: {e}")

    # ── Layer 3: card_back_img → pytesseract (wide sweep) ────────────────────
    #
    # card_back_img may be:
    #   A) An embedded card-back JPEG (~1968x3150, aspect ~0.62) — FIN at y 62-67%
    #   B) A full-page fitz render (~2500x3500, aspect ~0.71) — FIN at y 57-60%
    #
    # Detect by aspect ratio and try matching range first, then full sweep.
    try:
        cw, ch = card_back_img.size
        aspect = cw / ch
        print(f"[fin] Layer-3 card_back_img size={cw}x{ch} aspect={aspect:.3f}")

        if aspect < 0.67:
            # Narrow image = card-back only JPEG: FIN is lower in the frame
            y_ranges = [(0.620, 0.670), (0.605, 0.690), (0.590, 0.710),
                        (0.555, 0.730), (0.540, 0.750)]
        else:
            # Wider image = full-page render: same y-range as Layer 2
            y_ranges = [(0.570, 0.596), (0.555, 0.615), (0.540, 0.630),
                        (0.620, 0.670), (0.590, 0.700)]

        for y0, y1 in y_ranges:
            strip = card_back_img.crop((int(cw * 0.55), int(ch * y0), cw, int(ch * y1)))
            sw, sh = strip.size
            if sh < 80:
                scale = max(1, 80 // sh + 1)
                strip = strip.resize((sw * scale, sh * scale), _PILImage.LANCZOS)
            ocr_text = _ocr_strip(strip)
            result = _parse(ocr_text)
            if result:
                print(f"[fin] Layer-3 (y={y0:.3f}-{y1:.3f}) SUCCESS: {result}")
                return result
        print(f"[fin] Layer-3 exhausted all y-ranges for aspect={aspect:.3f}")
    except Exception as e:
        print(f"[fin] Layer-3 error: {e}")

    print("[fin] All layers exhausted — FIN not found")
    return ""


def extract_from_fayda_pdf(pdf_bytes: bytes) -> dict:
    """
    Master function: given raw PDF bytes of a Fayda ID card PDF,
    returns a dict with:
      {
        "success": True/False,
        "error": str or None,
        "api_data": dict compatible with merge_to_template(),
        "unique_id": str (FCN),
        "parsed_fields": dict (human-readable extracted fields),
        "photo_img": PIL.Image or None,
        "qr_img": PIL.Image or None,
        "qr_data": str (decoded QR content),
      }
    """
    result = {
        "success": False,
        "error": None,
        "api_data": {},
        "unique_id": "",
        "parsed_fields": {},
        "photo_img": None,
        "qr_img": None,
        "qr_data": "",
        "qr_crop_img": None,
        "fin": "",
    }

    # ── Step 1: Extract all images  ───────────────────────────────────────────
    images = _extract_images_from_pdf(pdf_bytes)

    photo_img = None
    qr_img = None

    if len(images) >= 5:
        # index 3 = portrait photo (413×531 px, rgb jpeg)
        # index 4 = QR code       (250×250 px, gray jpeg)
        # We identify by size: photo is portrait (tall), QR is square ~250×250
        # NOTE: the watermark/star-logo masks (361×350) also pass a loose
        # "square-ish" test, so we collect ALL square candidates and pick
        # the one closest to the expected 250×250 QR size (and try decoding
        # each as a tiebreaker / verification).
        qr_candidates = []
        for img in images:
            w, h = img.size
            is_square = abs(w - h) < 30
            is_portrait = (h > w) and (w > 100) and (h > 200) and not is_square
            is_qr_size = is_square and 150 < w < 800

            if is_portrait and photo_img is None:
                photo_img = img
            elif is_qr_size:
                qr_candidates.append(img)

        if qr_candidates:
            # Prefer whichever candidate actually decodes as a QR code
            decodable = [c for c in qr_candidates if _decode_qr(c)]
            if decodable:
                # If multiple decode, prefer the largest (real QR tends to be
                # higher-res than tiny watermark/logo masks)
                qr_img = max(decodable, key=lambda im: im.size[0])
            else:
                # Nothing decodes; fall back to size closest to canonical 250x250
                qr_img = min(qr_candidates, key=lambda im: abs(im.size[0] - 250) + abs(im.size[1] - 250))

    # Also try positional fallback: img[3] and img[4] as in the known layout
    if photo_img is None and len(images) > 3:
        candidate = images[3]
        w, h = candidate.size
        if h > w:  # portrait-oriented
            photo_img = candidate

    if qr_img is None and len(images) > 4:
        candidate = images[4]
        w, h = candidate.size
        if abs(w - h) < 50:  # roughly square
            qr_img = candidate

    result["photo_img"] = photo_img
    result["qr_img"] = qr_img

    # ── Step 2: Decode QR  ────────────────────────────────────────────────────
    qr_data = ""
    if qr_img is not None:
        qr_data = _decode_qr(qr_img)
    result["qr_data"] = qr_data

    # ── Step 2b: Card back — coordinate-based QR crop + FIN OCR  ─────────────
    # The card-back image (last extracted image, ~1968x3150) contains a
    # large QR (top) and the "FIN ####.####.####" line (below it, right
    # side). We crop these areas by fixed coordinates rather than decoding.
    card_back_img = None
    large_imgs = [im for im in images if im.size[0] > 1000 and im.size[1] > 1000]
    if large_imgs:
        # Card back is typically the last large image (card front comes
        # before it in the extracted order)
        card_back_img = large_imgs[-1]

    # Fallback: if no large embedded image found, render last PDF page with
    # fitz at high DPI — this always works regardless of how the PDF embeds
    # its images (some Fayda PDFs store the card back as a page, not an xref).
    if card_back_img is None and pdf_bytes:
        try:
            import fitz as _fitz
            doc = _fitz.open(stream=pdf_bytes, filetype="pdf")
            page = doc[-1]  # last page = card back panel
            mat = _fitz.Matrix(3.0, 3.0)  # ~216 DPI — enough for QR + FIN OCR
            pix = page.get_pixmap(matrix=mat)
            card_back_img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            print(f"[card_back] rendered from PDF page: {card_back_img.size}")
        except Exception as e:
            print(f"[card_back] fitz page render failed: {e}")

    qr_crop_img = None
    fin_value = ""
    if card_back_img is not None:
        try:
            qr_crop_img = _crop_qr_from_card_back(card_back_img)
        except Exception as e:
            print(f"[qr crop] {e}")
        try:
            fin_value = _extract_fin_from_card_back(card_back_img, pdf_bytes=pdf_bytes)
        except Exception as e:
            print(f"[fin ocr] {e}")

    result["qr_crop_img"] = qr_crop_img
    result["fin"] = fin_value

    # ── Step 3: Extract and parse text  ───────────────────────────────────────
    text = _extract_text_from_pdf(pdf_bytes)
    parsed = _parse_fayda_text(text)
    parsed["fin"] = fin_value or parsed.get("fin", "")
    result["parsed_fields"] = parsed

    # ── Step 4: Encode photo + QR crop to base64  ─────────────────────────────
    photo_b64 = ""
    if photo_img is not None:
        try:
            buf = io.BytesIO()
            photo_img.convert("RGB").save(buf, format="JPEG", quality=92)
            photo_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception as e:
            result["error"] = f"Photo encode error: {e}"

    qr_crop_b64 = ""
    if qr_crop_img is not None:
        try:
            buf = io.BytesIO()
            qr_crop_img.convert("RGB").save(buf, format="JPEG", quality=92)
            qr_crop_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception as e:
            print(f"[qr crop encode] {e}")

    # ── Step 5: Build api_data  ───────────────────────────────────────────────
    api_data = _build_api_data(parsed, photo_b64, qr_data, qr_crop_b64)
    # Ensure FIN is in api_data — from OCR, text layer, or derived from FCN.
    # Last resort: Fayda FIN = last 12 digits of the 16-digit FCN.
    fcn = parsed.get("fcn", "")
    best_fin = fin_value or parsed.get("fin", "")
    if not best_fin and len(fcn) >= 12:
        best_fin = fcn[-12:]
        print(f"[fin] FCN-derived fallback: {best_fin}")
    if best_fin:
        api_data["fin"] = best_fin
    result["fin"] = best_fin
    result["api_data"] = api_data
    result["unique_id"] = parsed.get("fcn", "")

    # ── Step 6: Determine success  ────────────────────────────────────────────
    # We need at minimum: a name + photo
    has_name = bool(api_data["fullName"]["eng"] or api_data["fullName"]["amh"])
    has_photo = bool(photo_b64)

    if has_name or has_photo:
        result["success"] = True
    else:
        result["error"] = "Could not extract name or photo from PDF. Make sure you upload a valid Fayda ID card PDF."

    return result
