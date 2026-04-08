#!/usr/bin/env python3
"""
create_maps.py

Converts the province colourmap PNG into a countries PNG map and an imagemap file for use on 
the wiki. Countries are coloured according to the definitions in the game files, with subject 
nations given stripes of their own colour over the overlord's colour. 

Inputs:
  - country_definitions           : From common
  - 00_states.txt                 : From common/history/states
  - 00_subject_relationships.txt  : From common/history/diplomacy
  - provinces.png                 : From game/map_data
  - default.map                   : From game/map_data

Outputs:
  - World_map_[Version].png       : The generated map PNG.
  - map.imagemap                  : An imagemap file for the wiki, which references the generated PNG and defines clickable areas for each country.
"""

import re
import os
import cv2
import colorsys
import numpy as np
from PIL import Image
from collections import defaultdict

# GAME SETTINGS ----------- CHECK THESE ARE UP-TO-DATE

VERSION = 1.12
SUBJECT_TYPES = {"colony", "personal_union", "puppet", "chartered_company", "dominion", "vassal", "crown_land"} 
#Non-autonomous subject types only 

# GRAPHICS SETTINGS ------- TWEAK THESE TO CHANGE THE MAP STYLE

STROKE_COLOUR  = "#1a1a1a"
STROKE_WIDTH  = 2              # set 0 to hide borders, must be an integer
CONTOUR_EPS   = 1.5            # Douglas-Peucker simplification (pixels), raise for smaller files
DEFAULT_FILL  = "#888888"    # fallback if a country has no colour entry

DECENTRALIZED_FILL   = "#C8A882" 
DECENTRALIZED_STROKE_WIDTH = 4 # must be an integer 

SEA_FILL    = "#A3BEDB"
LAKE_FILL   = "#A3BEDB"
SEA_STROKE  = "#488CD6"
SEA_STROKE_WIDTH = 2

STRIPE_WIDTH = 15              # Subject-overlord stripes
STRIPE_OPACITY = 0.3
SHOW_SUBJECT_STRIPES = True    # If False, subject nations will be coloured with their own colour, and stripes will be their overlord's colour 

SHADOW_OFFSET_X = 12           # Drop shadow settings, set both offsets to 0 to disable
SHADOW_OFFSET_Y = 12
SHADOW_OPACITY = 0.3

MIN_CONTOUR_PIXELS = 500    
SKIP_TYPES = {"decentralized"} # These country types will be drawn but not given a link

# INPUT FILES -----------

COUNTRY_COLOURS = "input/country_definitions" # Found in common
COUNTRY_PROVINCES = "input/00_states.txt" # Found in common/history/states
SUBJECT_RELATIONSHIPS = "input/00_subject_relationships.txt" # Found in common/history/diplomacy
PROVINCE_PNG = "input/provinces.png" #Found in game/map_data
SEA_DETAILS = "input/default.map" #found in game/map_data
LOCALISATION_YAML = "input/countries_l_english.yml" #Found in localization/english (can be any language, but untested)

# OUTPUT FILES -----------

MAP_NAME = f"World_map_{int(VERSION * 100)}.png"
MAP_FILE = f"output/{MAP_NAME}"

IMAGEMAP_IMAGE = f"File:{MAP_NAME}"
IMAGEMAP_CAPTION = f"World map, as of version {VERSION}. Click on a country to go to its page."
IMAGEMAP_FILE = "output/map.imagemap" 

# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_hex_colour(raw: str) -> int:
    """ Accepts any of: "x0161E0", "X0161E0", "#0161E0", "0161E0" to return integer 0x0161E0"""
    clean = re.sub(r'^[xX#]', '', raw.strip())
    return int(clean, 16)

def int_to_hex_css(colour_int: int) -> str:
    return f"#{colour_int:06X}"

def css_to_rgb(css: str) -> np.ndarray:
    css = css.lstrip('#')
    return np.array([int(css[i:i+2], 16) for i in (0, 2, 4)], dtype=np.uint8)

def parse_country_colour(value:dict) -> str:
    r, g, b = value["colour"]
    return f"#{int(r):02X}{int(g):02X}{int(b):02X}"
    
def get_country_type(value) -> str:
    return value.get("type", "")

def parse_map_colours(filepath: str) -> dict[str, set[int]]:
    result: dict[str, set[int]] = {}
    current_block = None
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            block_match = re.match(r'^(\w+)\s*=\s*\{', line)
            if block_match:
                current_block = block_match.group(1)
                result[current_block] = set()
                if "}" in line:
                    current_block = None
                continue
            if current_block:
                if "}" in line:
                    current_block = None
                    continue
                # Strip inline comments
                line = line.split("#")[0]
                for token in re.findall(r'[xX][0-9A-Fa-f]{6}', line):
                    result[current_block].add(parse_hex_colour(token))
    return result

def expand_mask(mask, width: int):
    width = int(width)
    if width <= 1:
        return mask
    out = mask.copy()
    for _ in range(width - 1):
        out |= np.roll(out, 1, axis=0)
        out |= np.roll(out, -1, axis=0)
        out |= np.roll(out, 1, axis=1)
        out |= np.roll(out, -1, axis=1)
    return out

print("1. Getting country provinces")

with open(COUNTRY_PROVINCES, "r", encoding="utf-8") as f:
    text = f.read()

country_pattern = re.compile(r'country\s*=\s*c:(\w+)')
province_pattern = re.compile(r'owned_provinces\s*=\s*\{([^}]*)\}', re.S)

countries = country_pattern.findall(text)
province_blocks = province_pattern.findall(text)

country_provinces = defaultdict(list)

for country, block in zip(countries, province_blocks):
    provinces = re.findall(r'x[0-9A-Fa-f]+', block)
    country_provinces[country].extend(provinces)

for country in country_provinces:
    seen = set()
    deduped = []
    for p in country_provinces[country]:
        if p not in seen:
            seen.add(p)
            deduped.append(p)
    country_provinces[country] = deduped

print("2. Getting subject/overlord relationships")

subject_to_overlord = {}

brace_stack = []
current_overlord = None
block_lines: list[str] = []

with open(SUBJECT_RELATIONSHIPS, encoding="utf-8") as f:
    for line in f:
        line_stripped = line.strip()
        
        # Detect new overlord block
        m = re.match(r'(c:\w+)\s*\?=\s*\{', line_stripped)
        if m:
            current_overlord = m.group(1)[2:] #Remove the "c:" prefix
            brace_stack.append(1) 
            block_lines = []
            continue
        
        if current_overlord is not None:
            block_lines.append(line)
            brace_stack[-1] += line.count("{")
            brace_stack[-1] -= line.count("}")
            
            if brace_stack[-1] == 0:
                pact_pattern = re.compile(
                    r'create_diplomatic_pact\s*=\s*\{.*?country\s*=\s*(c:\w+).*?type\s*=\s*(\w+).*?\}',
                    re.S
                )
                block_text = "\n".join(block_lines)
                for pact in pact_pattern.finditer(block_text):
                    subject = pact.group(1)[2:]
                    pact_type = pact.group(2)
                    if pact_type in SUBJECT_TYPES:
                        subject_to_overlord[subject] = current_overlord
                brace_stack.pop()
                current_overlord = None

def get_top_overlord(sub, mapping):
    while sub in mapping and mapping[sub] != sub:
        sub = mapping[sub]
    return sub

final_mapping = {sub: get_top_overlord(sub, subject_to_overlord) for sub in subject_to_overlord}

print("3. Loading country colours")

colour_pattern = re.compile(
    r'(\w+)\s*=\s*\{[^}]*?colour\s*=\s*'
    r'(?:hsv360\{\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\}'   
    r'|hsv\{\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\}'        
    r'|\{\s*(\d+)\s+(\d+)\s+(\d+)\s*\})'                   
    r'[^}]*?country_type\s*=\s*(\w+)',                     
    re.S
)

colour_mapping = {}

for filename in os.listdir(COUNTRY_COLOURS):
    if not filename.endswith(".txt"): continue
    path = os.path.join(COUNTRY_COLOURS, filename)

    current_country = None
    brace_level = 0
    block_lines = []

    with open(path) as f:
        for line in f:
            line_clean = re.sub(r'#.*', '', line).strip()
            if not line_clean: continue

            if current_country is None:
                m = re.match(r'(\w+)\s*=\s*\{', line_clean)
                if m:
                    current_country = m.group(1)
                    brace_level = 1
                    block_lines = []
                    continue

            if current_country is not None:
                block_lines.append(line_clean)
                brace_level += line_clean.count("{")
                brace_level -= line_clean.count("}")

                if brace_level == 0:
                    block_text = "\n".join(block_lines)

                    color_match = re.search(
                        r'color\s*=\s*(?:'
                        r'hsv360\s*\{\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\}|'
                        r'hsv\s*\{\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\}|'
                        r'\{\s*(\d+)\s+(\d+)\s+(\d+)\s*\}'
                        r')', block_text, re.S
                    )

                    if color_match:
                        if color_match.group(1):  # HSV360
                            h, s, v = float(color_match.group(1)), float(color_match.group(2)), float(color_match.group(3))
                            r, g, b = colorsys.hsv_to_rgb(h/360, s/100, v/100)
                        elif color_match.group(4):  # HSV
                            h, s, v = float(color_match.group(4)), float(color_match.group(5)), float(color_match.group(6))
                            r, g, b = colorsys.hsv_to_rgb(h, s, v)
                        else:  # RGB
                            r, g, b = int(color_match.group(7)), int(color_match.group(8)), int(color_match.group(9))
                        color = [int(c*255) if isinstance(c, float) else c for c in (r, g, b)]
                    else:
                        color = None #type: ignore

                    type_match = re.search(r'country_type\s*=\s*(\w+)', block_text)
                    country_type = type_match.group(1) if type_match else None

                    colour_mapping[current_country] = {"colour": color, "type": country_type}

                    current_country = None
                    block_lines = []
                    brace_level = 0

colour_mapping = {k: v for k, v in colour_mapping.items() if v["colour"] is not None}

for subject, overlord in final_mapping.items():
    if SHOW_SUBJECT_STRIPES:
        colour_mapping[subject]["stripes"] = colour_mapping[subject]["colour"]
        colour_mapping[subject]["colour"] = colour_mapping[overlord]["colour"]
    else:
        colour_mapping[subject]["stripes"] = colour_mapping[overlord]["colour"]

print("4. Loading provinces image and localisation")
img_pil = Image.open(PROVINCE_PNG).convert("RGB")
img = np.array(img_pil) 
H, W = img.shape[:2]

print(f"IMAGE SIZE: {W}×{H} px")

with open(LOCALISATION_YAML, encoding="utf-8-sig") as f:
    raw = f.read()

localisation = {}
for line in raw.splitlines():
    m = re.match(r'^\s+(\w+):\d*\s+"(.+)"', line)
    if m:
        localisation[m.group(1)] = m.group(2)

# Build a fast colour to country lookup to avoid O(N) scans per country.

print("5. Building colour lookup")

img_packed = (
    img[:, :, 0].astype(np.int32) * 65536 +
    img[:, :, 1].astype(np.int32) * 256   +
    img[:, :, 2].astype(np.int32)
)

province_int_to_country: dict[int, str] = {}
for country_tag, colour_list in country_provinces.items():
    for raw in colour_list:
        province_int_to_country[parse_hex_colour(raw)] = country_tag

# Duplicate province colours exist across countries, so some pixels may be mis-assigned

print("6. Assigning pixels to countries")

all_countries = list(country_provinces.keys())
country_to_idx = {tag: i + 1 for i, tag in enumerate(all_countries)}

lut = np.zeros(0x1000000, dtype=np.int32)

for colour_int, country_tag in province_int_to_country.items():
    if colour_int < 0x1000000:  
        lut[colour_int] = country_to_idx[country_tag]

country_map = lut[img_packed]

print("7. Loading sea/lake tiles")
map_blocks = parse_map_colours(SEA_DETAILS)
sea_ints = map_blocks.get("sea_starts", set())
lake_ints = map_blocks.get("lakes", set())

# Special indices for seas/lakes
SEA_IDX  = len(all_countries) + 1
LAKE_IDX = len(all_countries) + 2

for colour_int in sea_ints:
    if colour_int < 0x1000000: lut[colour_int] = SEA_IDX
for colour_int in lake_ints:
    if colour_int < 0x1000000: lut[colour_int] = LAKE_IDX

country_map = lut[img_packed]

print("8. Rendering PNG")

sea_rgb = css_to_rgb(SEA_FILL)
lake_rgb = css_to_rgb(LAKE_FILL)
stroke_rgb = css_to_rgb(STROKE_COLOUR)
default_rgb = css_to_rgb(DEFAULT_FILL)
decentralized_fill_rgb = css_to_rgb(DECENTRALIZED_FILL)

# LUTs for countries
max_idx = country_map.max()
fill_lut = np.tile(default_rgb, (max_idx + 1, 1))
border_lut = np.tile(stroke_rgb, (max_idx + 1, 1))
is_decentralized_lut = np.zeros(max_idx + 1, dtype=bool)

for tag, idx in country_to_idx.items():
    data = colour_mapping.get(tag, {})
    ctype = get_country_type(data)
    if ctype == "decentralized":
        fill_lut[idx] = decentralized_fill_rgb
        is_decentralized_lut[idx] = True
        r, g, b = data["colour"] #type: ignore
        border_lut[idx] = (int(r), int(g), int(b)) 
    elif data:
        r, g, b = data["colour"] #type: ignore
        fill_lut[idx] = (int(r), int(g), int(b)) 

# Fills
display = fill_lut[country_map]

sea_mask = np.isin(img_packed, list(sea_ints))
lake_mask = np.isin(img_packed, list(lake_ints))
ocean_mask = sea_mask | lake_mask

display[sea_mask] = sea_rgb
display[lake_mask] = lake_rgb

# Stripe LUTs
y, x = np.indices((H, W))
stripe_pattern = (x // STRIPE_WIDTH) % 2 == 0

stripe_lut = np.zeros((max_idx + 1, 3), dtype=np.uint8)
has_stripes_lut = np.zeros(max_idx + 1, dtype=bool)

for tag, idx in country_to_idx.items():
    data = colour_mapping.get(tag, {})
    stripes = data.get("stripes")
    if stripes:
        r, g, b = stripes #type: ignore
        stripe_lut[idx] = (int(r), int(g), int(b))
        has_stripes_lut[idx] = True

mask = has_stripes_lut[country_map] & stripe_pattern
stripe_colours = stripe_lut[country_map[mask]].astype(float)
display[mask] = ((1 - STRIPE_OPACITY) * display[mask].astype(float) + STRIPE_OPACITY * stripe_colours).astype(np.uint8)

# Add drop shadows

land_mask = ~ocean_mask
shifted = np.zeros_like(land_mask)
shifted[SHADOW_OFFSET_Y:, :W - SHADOW_OFFSET_X] = land_mask[:H - SHADOW_OFFSET_Y, SHADOW_OFFSET_X:]

display[shifted & ~land_mask] = (display[shifted & ~land_mask].astype(float) * (1 - SHADOW_OPACITY)).astype(np.uint8)

# Detect borders 
region_map = country_map.copy()
border_h = region_map[:-1, :] != region_map[1:, :]
border_v = region_map[:, :-1] != region_map[:, 1:]

all_borders = np.zeros((H, W), dtype=bool)
all_borders[:-1, :] |= border_h
all_borders[1:, :]  |= border_h
all_borders[:, :-1] |= border_v
all_borders[:, 1:]  |= border_v

# Ocean borders with each other
ocean_map = np.zeros_like(region_map, dtype=np.uint16)  # 0 = land
for i, colour_int in enumerate(sea_ints | lake_ints, start=1):
    ocean_map[img_packed == colour_int] = i

border_h = ocean_map[:-1, :] != ocean_map[1:, :]
border_v = ocean_map[:, :-1] != ocean_map[:, 1:]

sea_lake_border = np.zeros((H, W), dtype=bool)
sea_lake_border[:-1, :] |= border_h
sea_lake_border[1:, :]  |= border_h
sea_lake_border[:, :-1] |= border_v
sea_lake_border[:, 1:]  |= border_v

sea_lake_border &= ocean_map > 0

display[sea_lake_border] = css_to_rgb(SEA_STROKE)

# Ocean borders with land

land_ocean_border = all_borders & ((land_mask & ocean_mask) |
                                   (np.roll(land_mask, 1, axis=0) & np.roll(ocean_mask, 1, axis=0)) |
                                   (np.roll(land_mask, 1, axis=1) & np.roll(ocean_mask, 1, axis=1)))
display[land_ocean_border] = stroke_rgb

# Decentralized borders
valid_mask = region_map <= max_idx
decentralized_pixels = np.zeros_like(region_map, dtype=bool)
decentralized_pixels[valid_mask] = is_decentralized_lut[region_map[valid_mask]]
decentralized_borders = all_borders & decentralized_pixels

expanded_decentralized = expand_mask(decentralized_borders, DECENTRALIZED_STROKE_WIDTH)
display[expanded_decentralized & valid_mask] = border_lut[region_map[expanded_decentralized & valid_mask]]

# Normal land borders
normal_borders = all_borders & ~decentralized_pixels & ~ocean_mask
expanded_normal = expand_mask(normal_borders, STROKE_WIDTH)
display[expanded_normal] = stroke_rgb

Image.fromarray(display).save(MAP_FILE)
print(f"Wrote {MAP_FILE}!")

print("9. Building imagemap")

lines = [
    "<imagemap>",
    f"{IMAGEMAP_IMAGE}|{IMAGEMAP_CAPTION}",
    "",
]

for country_tag in all_countries:
    idx = country_to_idx[country_tag]
    binary = np.where(country_map == idx, np.uint8(255), np.uint8(0))
    if not np.any(binary):
        continue

    country_data = colour_mapping.get(country_tag, {})
    if get_country_type(country_data) in SKIP_TYPES:
        continue

    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        continue

    name = localisation.get(country_tag, country_tag)
    safe_name = name.replace("[", "").replace("]", "").replace("|", "")
    url_name  = safe_name.replace(" ", "_")

    for cnt in contours:
        if cv2.contourArea(cnt) < MIN_CONTOUR_PIXELS:
            area = int(cv2.contourArea(cnt))
            #print(f"Skipping exclave of {country_tag} ({name}) — {area}px")
            continue
        approx = cv2.approxPolyDP(cnt, CONTOUR_EPS, closed=True)
        if len(approx) < 3:
            continue
        coords = " ".join(f"{int(x)} {int(y)}" for x, y in approx.reshape(-1, 2))
        coords = coords.replace("455", "454")  # Replace the number 455 to prevent MediaWiki from triggering the abuse filter because it thinks 455 is code for "ass"
        lines.append(f"poly {coords} [[{url_name}|{safe_name}]]")

lines += [
    "",
    "</imagemap>",
]

with open(IMAGEMAP_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"Wrote {IMAGEMAP_FILE}!")