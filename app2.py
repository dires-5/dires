import os
from flask import Flask, render_template_string, request, send_file
from PIL import Image, ImageDraw

# ===== SETTINGS =====
A4_WIDTH = 2480
A4_HEIGHT = 3508

CARD_WIDTH = 2191
CARD_HEIGHT = 667

MAX_PER_PAGE = 5
DPI = 300

OUTPUT_FOLDER = "output"

CROP_LENGTH = 40
CROP_WIDTH = 3
CROP_OFFSET = 15
CENTER_MARK_LENGTH = 80

# ---------------------------

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>PVC ID Card Generator</title>
<style>
body { font-family: Arial, sans-serif; background: #f4f6f8; margin: 0; padding: 0; }
.container { max-width: 750px; margin: 50px auto; background: #fff; padding: 30px; border-radius: 12px; box-shadow: 0 5px 20px rgba(0,0,0,0.1);}
h1 { font-size: 28px; font-weight: bold; margin-bottom: 20px; }
p { color: #555; }
input[type=file] { width: 100%; padding: 6px; margin-bottom: 20px; }
button { padding: 12px 20px; background: #007bff; color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: 16px; width: 100%; }
button:hover { background: #0056b3; }
label { font-weight: 500; }
.preview { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 20px; }
.preview img { width: 120px; height: 37px; object-fit: cover; border: 1px solid #ccc; border-radius: 4px; }
.alert { padding: 15px; background: #d4edda; color: #155724; border-radius: 6px; margin-top: 20px; }
a.download-btn { padding: 8px 14px; background: #28a745; color: #fff; text-decoration: none; border-radius: 5px; margin-left: 10px; }
a.download-btn:hover { background: #218838; }
</style>
<script>
function previewImages() {
    const preview = document.getElementById('preview');
    preview.innerHTML = '';
    const files = document.getElementById('files').files;
    for(let i=0; i<files.length; i++){
        const reader = new FileReader();
        reader.onload = function(e){
            const img = document.createElement('img');
            img.src = e.target.result;
            preview.appendChild(img);
        }
        reader.readAsDataURL(files[i]);
    }
}
</script>
</head>
<body>
<div class="container">
<h1>PVC ID Card Generator</h1>
<p>Upload 2191x667 px images to generate A4 PVC PDF & PNGs with crop marks and center guides.</p>
<form method="post" enctype="multipart/form-data">
<input type="file" name="files" id="files" multiple onchange="previewImages()" required>
<div class="preview" id="preview"></div>
<label><input type="checkbox" name="mirror"> Mirror Horizontally</label><br><br>
<button type="submit">Generate PDF & PNGs</button>
</form>
{% if message %}
<div class="alert">{{ message|safe }}</div>
{% endif %}
</div>
</body>
</html>
"""

app = Flask(__name__)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# ----- Your functions (unchanged) -----
def draw_crop_marks(draw, x, y):
    draw.line((x - CROP_OFFSET, y - CROP_LENGTH, x - CROP_OFFSET, y - CROP_OFFSET), fill="black", width=CROP_WIDTH)
    draw.line((x - CROP_LENGTH, y - CROP_OFFSET, x - CROP_OFFSET, y - CROP_OFFSET), fill="black", width=CROP_WIDTH)
    draw.line((x + CARD_WIDTH + CROP_OFFSET, y - CROP_LENGTH, x + CARD_WIDTH + CROP_OFFSET, y - CROP_OFFSET), fill="black", width=CROP_WIDTH)
    draw.line((x + CARD_WIDTH + CROP_OFFSET, y - CROP_OFFSET, x + CARD_WIDTH + CROP_LENGTH, y - CROP_OFFSET), fill="black", width=CROP_WIDTH)
    draw.line((x - CROP_OFFSET, y + CARD_HEIGHT + CROP_OFFSET, x - CROP_OFFSET, y + CARD_HEIGHT + CROP_LENGTH), fill="black", width=CROP_WIDTH)
    draw.line((x - CROP_LENGTH, y + CARD_HEIGHT + CROP_OFFSET, x - CROP_OFFSET, y + CARD_HEIGHT + CROP_OFFSET), fill="black", width=CROP_WIDTH)
    draw.line((x + CARD_WIDTH + CROP_OFFSET, y + CARD_HEIGHT + CROP_OFFSET, x + CARD_WIDTH + CROP_OFFSET, y + CARD_HEIGHT + CROP_LENGTH), fill="black", width=CROP_WIDTH)
    draw.line((x + CARD_WIDTH + CROP_OFFSET, y + CARD_HEIGHT + CROP_OFFSET, x + CARD_WIDTH + CROP_LENGTH, y + CARD_HEIGHT + CROP_OFFSET), fill="black", width=CROP_WIDTH)

def draw_center_marks(draw):
    center_x = A4_WIDTH // 2
    center_y = A4_HEIGHT // 2
    draw.line((center_x, 0, center_x, CENTER_MARK_LENGTH), fill="black", width=CROP_WIDTH)
    draw.line((center_x, A4_HEIGHT - CENTER_MARK_LENGTH, center_x, A4_HEIGHT), fill="black", width=CROP_WIDTH)
    draw.line((0, center_y, CENTER_MARK_LENGTH, center_y), fill="black", width=CROP_WIDTH)
    draw.line((A4_WIDTH - CENTER_MARK_LENGTH, center_y, A4_WIDTH, center_y), fill="black", width=CROP_WIDTH)

# ----- Flask route -----
@app.route("/", methods=["GET", "POST"])
def index():
    message = None
    if request.method == "POST":
        files = request.files.getlist("files")
        mirror = "mirror" in request.form

        images = []
        for file in files:
            img = Image.open(file.stream).convert("RGB")
            if img.size == (CARD_WIDTH, CARD_HEIGHT):
                if mirror:
                    img = img.transpose(Image.FLIP_LEFT_RIGHT)
                images.append(img)

        if images:
            pages = []
            left_margin = (A4_WIDTH - CARD_WIDTH) // 2
            total_cards_height = MAX_PER_PAGE * CARD_HEIGHT
            remaining_space = A4_HEIGHT - total_cards_height
            vertical_gap = remaining_space // (MAX_PER_PAGE + 1)

            page_number = 1
            page = Image.new("RGB", (A4_WIDTH, A4_HEIGHT), "white")
            draw = ImageDraw.Draw(page)
            count = 0

            for card in images:
                if count == MAX_PER_PAGE:
                    draw_center_marks(draw)
                    png_path = os.path.join(OUTPUT_FOLDER, f"A4_page_{page_number}.png")
                    page.save(png_path, dpi=(DPI,DPI))
                    pages.append(page)
                    page_number += 1
                    page = Image.new("RGB", (A4_WIDTH, A4_HEIGHT), "white")
                    draw = ImageDraw.Draw(page)
                    count = 0

                x = left_margin
                y = vertical_gap + count * (CARD_HEIGHT + vertical_gap)
                page.paste(card, (x, y))
                draw_crop_marks(draw, x, y)
                count += 1

            if count > 0:
                draw_center_marks(draw)
                png_path = os.path.join(OUTPUT_FOLDER, f"A4_page_{page_number}.png")
                page.save(png_path, dpi=(DPI,DPI))
                pages.append(page)

            pdf_path = os.path.join(OUTPUT_FOLDER, "A4_ID_Cards_PVC_READY.pdf")
            pages[0].save(pdf_path, save_all=True, append_images=pages[1:], format="PDF", resolution=DPI)

            message = f"PDF & PNGs generated in '{OUTPUT_FOLDER}' folder. <a href='/download_pdf' class='download-btn'>Download PDF</a>"

    return render_template_string(HTML, message=message)

@app.route("/download_pdf")
def download_pdf():
    pdf_path = os.path.join(OUTPUT_FOLDER, "A4_ID_Cards_PVC_READY.pdf")
    return send_file(pdf_path, as_attachment=True, download_name="A4_ID_Cards_PVC_READY.pdf", mimetype="application/pdf")

if __name__ == "__main__":
    app.run(debug=True)
