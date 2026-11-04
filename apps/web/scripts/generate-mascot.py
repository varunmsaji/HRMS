"""Generate the Krewoxa penguin mascot SVGs (one file per pose)."""
import os, sys

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "public", "mascot")
os.makedirs(OUT, exist_ok=True)

NAVY, INK, CYAN, BLUE = "#0B3D91", "#141A2B", "#00C6FF", "#1E6BFF"

DEFS = f"""<defs>
  <linearGradient id="kp-body" x1="0.2" y1="0" x2="0.8" y2="1">
    <stop offset="0" stop-color="#34405F"/><stop offset="0.55" stop-color="#1A2135"/><stop offset="1" stop-color="#0C101C"/>
  </linearGradient>
  <linearGradient id="kp-fl" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#2C3651"/><stop offset="1" stop-color="#0E1322"/>
  </linearGradient>
  <radialGradient id="kp-belly" cx="0.42" cy="0.32" r="0.8">
    <stop offset="0" stop-color="#FFFFFF"/><stop offset="0.7" stop-color="#F3F6FB"/><stop offset="1" stop-color="#DCE3EE"/>
  </radialGradient>
  <linearGradient id="kp-beak" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#FFC24A"/><stop offset="1" stop-color="#FF8A1F"/>
  </linearGradient>
  <radialGradient id="kp-chest" cx="0.5" cy="0.5" r="0.5">
    <stop offset="0" stop-color="#FFD873" stop-opacity="0.55"/><stop offset="1" stop-color="#FFD873" stop-opacity="0"/>
  </radialGradient>
  <linearGradient id="kp-brand" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="{NAVY}"/><stop offset="1" stop-color="{BLUE}"/>
  </linearGradient>
</defs>"""

FLIPPER = "M-7 0 C-24 22,-27 62,-15 92 C-10 101,-1 99,3 88 C11 62,14 26,8 0 Z"
L_SH, R_SH = (62, 132), (178, 132)

def flipper(side, angle, sy=1.0):
    x, y = L_SH if side == "L" else R_SH
    mirror = "" if side == "L" else " scale(-1,1)"
    a = angle if side == "L" else -angle
    # angle > 0 swings the tip outward/up for both sides
    return (f'<g transform="translate({x} {y}) rotate({a}){mirror} scale(1 {sy})">'
            f'<path d="{FLIPPER}" fill="url(#kp-fl)"/>'
            f'<path d="M5 6 C10 30,8 60,1 84" fill="none" stroke="#fff" stroke-opacity=".08" stroke-width="3" stroke-linecap="round"/></g>')

def eyes(kind="open"):
    if kind == "closed":
        return "".join(f'<path d="M{x-9} 97 Q{x} 87 {x+9} 97" fill="none" stroke="{INK}" stroke-width="3.6" stroke-linecap="round"/>' for x in (101, 139))
    out = ""
    for x in (101, 139):
        out += (f'<ellipse cx="{x}" cy="95" rx="8.5" ry="9.5" fill="{INK}"/>'
                f'<circle cx="{x+3}" cy="91.5" r="3.2" fill="#fff"/>'
                f'<circle cx="{x-3}" cy="99" r="1.4" fill="#fff" opacity=".8"/>')
    return out

def glasses():
    frame = NAVY
    out = (f'<path d="M87 93 L71 89" stroke="{frame}" stroke-width="2.6" stroke-linecap="round"/>'
           f'<path d="M153 93 L169 89" stroke="{frame}" stroke-width="2.6" stroke-linecap="round"/>'
           f'<path d="M114.5 92 Q120 87.5 125.5 92" fill="none" stroke="{frame}" stroke-width="2.6" stroke-linecap="round"/>')
    for x in (101, 139):
        out += (f'<circle cx="{x}" cy="95" r="14" fill="#BFEFFF" fill-opacity=".14" stroke="{frame}" stroke-width="2.8"/>'
                f'<path d="M{x-9} 88 A10.5 10.5 0 0 1 {x+2} 84.5" fill="none" stroke="#fff" stroke-opacity=".75" stroke-width="2" stroke-linecap="round"/>')
    return out

def brows(kind):
    if kind == "think":
        return (f'<path d="M90 74 Q99 69 108 72" fill="none" stroke="{INK}" stroke-width="3" stroke-linecap="round"/>'
                f'<path d="M131 69 Q140 62 150 67" fill="none" stroke="{INK}" stroke-width="3" stroke-linecap="round"/>')
    return ""

BADGE_FACE = """<rect x="103" y="169" width="34" height="34" rx="6" fill="url(#kp-brand)"/>
  <path d="M112.5 176.5 V195.5 M112.5 187.5 L127 176.5 M117.5 183.7 L128 195.5" fill="none" stroke="#fff" stroke-width="4.6" stroke-linecap="round" stroke-linejoin="round"/>
  <rect x="106" y="208" width="28" height="4" rx="2" fill="#94A3B8"/>"""

def penguin(front="", back="", fl=("L", 14), fr=("R", 14), eye="open", brow="", extra_top="", over="", badge=True):
    fls = [flipper(*fl) if fl else "", flipper(*fr) if fr else ""]
    return f"""
  <ellipse cx="120" cy="274" rx="66" ry="7" fill="{NAVY}" opacity=".13"/>
  {back}
  <path d="M120 36 C174 36 194 100 195 170 C196 234 164 266 120 266 C76 266 44 234 45 170 C46 100 66 36 120 36 Z" fill="url(#kp-body)"/>
  <path d="M120 72 C106 56 72 60 72 92 C72 112 86 120 92 124 C78 146 70 172 70 205 C70 242 94 258 120 258 C146 258 170 242 170 205 C170 172 162 146 148 124 C154 120 168 112 168 92 C168 60 134 56 120 72 Z" fill="url(#kp-belly)"/>
  <ellipse cx="120" cy="140" rx="44" ry="22" fill="url(#kp-chest)"/>
  <path d="M181 74 C193 102 197 146 194 196" fill="none" stroke="{CYAN}" stroke-width="2.6" stroke-linecap="round" opacity=".75"/>
  <path d="M88 252 C80 262 82 272 96 272 L112 272 C118 272 118 264 112 258 Z" fill="#FF9F2E"/>
  <path d="M152 252 C160 262 158 272 144 272 L128 272 C122 272 122 264 128 258 Z" fill="#FF9F2E"/>
  <path d="M96 122 L120 168 L144 122" fill="none" stroke="{CYAN}" stroke-width="2.6" stroke-linejoin="round"/>
  <rect x="98" y="164" width="44" height="54" rx="6" fill="#fff" stroke="#94A3B8" stroke-width="1.5"/>
  {BADGE_FACE if badge else ""}
  {eyes(eye)}{glasses()}{brows(brow)}
  <ellipse cx="86" cy="110" rx="7" ry="4" fill="#FF8FA8" opacity=".35"/>
  <ellipse cx="154" cy="110" rx="7" ry="4" fill="#FF8FA8" opacity=".35"/>
  <path d="M109 106 Q120 100 131 106 Q126 117 120 118 Q114 117 109 106 Z" fill="url(#kp-beak)"/>
  <path d="M112 107 Q120 104 128 107" fill="none" stroke="#fff" stroke-opacity=".5" stroke-width="1.4" stroke-linecap="round"/>
  {front}
  {"".join(fls)}
  {over}
  {extra_top}"""

def svg(body, title, vb="0 0 240 290"):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" role="img" aria-label="{title}">'
            f'<title>{title}</title>{DEFS}{body}</svg>\n')

conf = [(28,60,"#00C6FF",20),(52,40,"#FF8FA8",-30),(196,48,"#1E6BFF",35),(214,86,"#FFB02E",-15),
        (18,120,"#1E6BFF",60),(222,140,"#00C6FF",-40),(40,96,"#FFB02E",15),(182,22,"#FF8FA8",70)]
confetti = "".join(f'<rect x="{x-4}" y="{y-2}" width="8" height="4" rx="1.5" fill="{c}" transform="rotate({r} {x} {y})"/>' for x,y,c,r in conf)

clip = f"""<g transform="rotate(-4 120 200)">
  <rect x="86" y="160" width="68" height="84" rx="8" fill="#fff" stroke="#CBD5E1" stroke-width="1.5"/>
  <rect x="106" y="154" width="28" height="12" rx="4" fill="{NAVY}"/>
  <circle cx="99" cy="186" r="5" fill="{BLUE}"/><path d="M96.5 186 l2 2 l3.5 -4" fill="none" stroke="#fff" stroke-width="1.6" stroke-linecap="round"/>
  <rect x="109" y="183" width="34" height="6" rx="3" fill="#CBD5E1"/>
  <circle cx="99" cy="204" r="5" fill="{BLUE}"/><path d="M96.5 204 l2 2 l3.5 -4" fill="none" stroke="#fff" stroke-width="1.6" stroke-linecap="round"/>
  <rect x="109" y="201" width="28" height="6" rx="3" fill="#CBD5E1"/>
  <circle cx="99" cy="222" r="5" fill="#CBD5E1"/>
  <rect x="109" y="219" width="32" height="6" rx="3" fill="#E2E8F0"/>
</g>"""

sign = f"""<g transform="rotate(-5 120 210)">
  <rect x="64" y="180" width="112" height="56" rx="9" fill="#fff" stroke="#CBD5E1" stroke-width="1.5"/>
  <text x="120" y="203" text-anchor="middle" font-family="Inter,Segoe UI,Helvetica,Arial,sans-serif" font-size="13" font-weight="700" fill="{NAVY}">Welcome to</text>
  <text x="120" y="224" text-anchor="middle" font-family="Inter,Segoe UI,Helvetica,Arial,sans-serif" font-size="17" font-weight="800" letter-spacing="1" fill="{BLUE}">KREWOXA</text>
</g>"""

bubble = f"""<circle cx="176" cy="54" r="4" fill="#fff" stroke="#CBD5E1"/>
<circle cx="186" cy="40" r="6" fill="#fff" stroke="#CBD5E1"/>
<rect x="188" y="6" width="46" height="26" rx="13" fill="#fff" stroke="#CBD5E1"/>
<circle cx="201" cy="19" r="3.2" fill="{BLUE}"/><circle cx="211" cy="19" r="3.2" fill="{BLUE}"/><circle cx="221" cy="19" r="3.2" fill="{BLUE}"/>"""

wave_lines = f'<path d="M222 36 Q230 46 226 58" fill="none" stroke="{CYAN}" stroke-width="3" stroke-linecap="round"/><path d="M230 26 Q242 44 236 64" fill="none" stroke="{CYAN}" stroke-width="3" stroke-linecap="round" opacity=".6"/>'
spark = f'<g stroke="#FFB02E" stroke-width="3" stroke-linecap="round"><path d="M214 66 L220 56"/><path d="M224 76 L234 72"/><path d="M204 58 L203 48"/></g>'

poses = {
  "standing":   penguin(),
  "waving":     penguin(fr=("R", 150), eye="closed", extra_top=wave_lines),
  "thinking":   penguin(fr=("R", -96, 0.5), brow="think", extra_top=bubble),
  "clipboard":  penguin(over=clip, fl=("L", -34, 0.75), fr=("R", -34, 0.75)),
  "celebrating":penguin(fl=("L", 150), fr=("R", 150), eye="closed", extra_top=confetti),
  "explaining": penguin(fr=("R", 128, 0.85), extra_top=spark),
  "welcome":    penguin(over=sign, fl=("L", -40, 0.8), fr=("R", -40, 0.8), eye="closed", badge=False),
}
# Holding the hero window: "holding" goes behind the window, "holding-hands" in front of it, so the
# flippers grip its top edge (at y=212). The tips are outlined because the window's top bar is as dark as they are.
def grip(side):
    x, y = L_SH if side == "L" else R_SH
    mirror = "" if side == "L" else " scale(-1,1)"
    a = -16 if side == "L" else 16
    return (f'<g transform="translate({x} {y}) rotate({a}){mirror} scale(1 1.04)">'
            f'<path d="{FLIPPER}" fill="url(#kp-fl)"/>'
            f'<path d="{FLIPPER}" fill="none" stroke="#DCE6FA" stroke-opacity=".75" stroke-width="1.6" clip-path="url(#kp-tip)"/></g>')

poses["holding"] = penguin(fl=None, fr=None)
poses["holding-hands"] = '<clipPath id="kp-tip"><rect x="-40" y="66" width="80" height="50"/></clipPath>' + grip("L") + grip("R")

for name, body in poses.items():
    with open(os.path.join(OUT, f"penguin-{name}.svg"), "w") as f:
        f.write(svg(body, f"Krewoxa penguin mascot — {name}"))
print("wrote", len(poses))
