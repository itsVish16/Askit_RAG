from PIL import Image
import sys

def autocrop(image_path):
    print(f"Processing {image_path}...")
    try:
        im = Image.open(image_path).convert("RGBA")
        # Get the alpha channel (a mask where transparent is 0)
        a_channel = im.getchannel("A")
        # Find the bounding box of non-zero alpha
        bbox = a_channel.getbbox()
        if bbox:
            im_cropped = im.crop(bbox)
            im_cropped.save(image_path)
            print(f"Success: Cropped {image_path} to {bbox}")
        else:
            print(f"Skipped {image_path}: No bounding box found.")
    except Exception as e:
        print(f"Error processing {image_path}: {e}")

autocrop("../frontend/public/logo.png")
autocrop("../frontend/public/logo-small.png")
