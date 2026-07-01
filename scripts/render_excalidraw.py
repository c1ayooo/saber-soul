"""
Excalidraw -> PNG local renderer.
V2: fix containers dict overwrite bug + viewBox quotes

Usage: python3 render_excalidraw.py <input.excalidraw> [output.png] [scale=2]
Depends: cairosvg (hermes-agent venv) + ~/.fonts/msyh.ttc

Known pitfalls:
1. containers dict: text elements with containerId must NOT overwrite existing shape entries.
   Always use `if el["containerId"] not in conts:` guard before setting placeholder.
2. SVG viewBox attribute: the closing quote is REQUIRED. `viewBox="0 0 {w} {h}"` NOT `viewBox="0 0 {w} {h}>`.
   Missing quote causes the SVG parser to treat the rest of the file as the viewBox value (blank canvas).
3. Chinese text: use `font-family="Microsoft YaHei, sans-serif"` in SVG. sans-serif alone is not enough.
"""
import json, math, os, sys

def pos(text_el, cont, fs):
    cx,cy = cont.get("x",0), cont.get("y",0)
    cw,ch = cont.get("width",100), cont.get("height",100)
    lines = text_el.get("text","").replace("\\n","\n").split("\n")
    lh = fs+4; mw = max(len(l) for l in lines) if lines else 1
    tx = cx + (cw - mw*fs*0.55)/2
    ty = cy + (ch - len(lines)*lh)/2 + fs
    return tx, ty, lines, lh

def render(inp, out, scale=2):
    with open(inp) as f: data = json.load(f)
    els = data.get("elements",[])
    ctxts, others, conts = [], [], {}
    for el in els:
        if el["type"]=="text" and el.get("containerId"):
            ctxts.append(el)
            if el["containerId"] not in conts: conts[el["containerId"]]=None
        else:
            others.append(el)
            if el.get("id"): conts[el["id"]]=el

    mx = [float("inf"),float("-inf")]; my = [float("inf"),float("-inf")]
    for el in els:
        if el["type"]=="text" and el.get("containerId"):
            c = conts.get(el["containerId"])
            if c:
                mx[0]=min(mx[0],c["x"]); mx[1]=max(mx[1],c["x"]+c["width"])
                my[0]=min(my[0],c["y"]); my[1]=max(my[1],c["y"]+c["height"]);
                continue
        ex,ey = el.get("x",0), el.get("y",0)
        ew = el.get("width",100) if el["type"]!="arrow" else 0
        eh = el.get("height",100) if el["type"]!="arrow" else 0
        mx[0]=min(mx[0],ex); mx[1]=max(mx[1],ex+ew)
        my[0]=min(my[0],ey); my[1]=max(my[1],ey+eh)
    pad=40; w=int(mx[1]-mx[0]+pad*2); h=int(my[1]-my[0]+pad*2)
    ox,oy = mx[0]-pad, my[0]-pad
    def px(x): return f"{x-ox:.0f}"
    def py(y): return f"{y-oy:.0f}"

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
           f'<rect width="{w}" height="{h}" fill="white"/>']
    for el in others:
        t,ex,ey = el["type"],el.get("x",0),el.get("y",0)
        ew,eh,bg,sc = el.get("width",100),el.get("height",100),el.get("backgroundColor","transparent"),el.get("strokeColor","#1e1e1e")
        sw = el.get("strokeWidth",2)
        if t=="rectangle":
            rx=8 if el.get("roundness",{}).get("type")==3 else 0
            svg.append(f'<rect x="{px(ex)}" y="{py(ey)}" width="{ew:.0f}" height="{eh:.0f}" rx="{rx}" fill="{bg}" stroke="{sc}" stroke-width="{sw}"/>')
        elif t=="ellipse":
            svg.append(f'<ellipse cx="{px(ex+ew/2)}" cy="{py(ey+eh/2)}" rx="{ew/2:.0f}" ry="{eh/2:.0f}" fill="{bg}" stroke="{sc}" stroke-width="{sw}"/>')
        elif t=="diamond":
            pts=f"{px(ex+ew/2)},{py(ey)} {px(ex+ew)},{py(ey+eh/2)} {px(ex+ew/2)},{py(ey+eh)} {px(ex)},{py(ey+eh/2)}"
            svg.append(f'<polygon points="{pts}" fill="{bg}" stroke="{sc}" stroke-width="{sw}"/>')
        elif t=="arrow":
            pts=el.get("points",[[0,0],[100,0]]); sx,sy=ex+pts[0][0],ey+pts[0][1]
            ex2,ey2=ex+pts[-1][0],ey+pts[-1][1]; dash="5,5" if el.get("strokeStyle")=="dashed" else "none"
            svg.append(f'<line x1="{px(sx)}" y1="{py(sy)}" x2="{px(ex2)}" y2="{py(ey2)}" stroke="{sc}" stroke-width="{sw}" stroke-dasharray="{dash}"/>')
            if el.get("endArrowhead")=="arrow":
                ang=math.atan2(ey2-sy,ex2-sx)
                svg.append(f'<polygon points="{px(ex2)},{py(ey2)} {px(ex2-10*math.cos(ang-0.4))},{py(ey2-10*math.sin(ang-0.4))} {px(ex2-10*math.cos(ang+0.4))},{py(ey2-10*math.sin(ang+0.4))}" fill="{sc}"/>')
        elif t=="text" and not el.get("containerId"):
            txt=el.get("text",""); fs=el.get("fontSize",16)
            if not txt.strip(): continue
            for li,l in enumerate(txt.replace("\\n","\n").split("\n")):
                svg.append(f'<text x="{px(ex+5)}" y="{py(ey+(li+1)*fs)}" font-size="{fs}" fill="{sc}" font-family="Microsoft YaHei,sans-serif">{l.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")}</text>')
    for tel in ctxts:
        txt=tel.get("text",""); fs=tel.get("fontSize",16)
        cont=conts.get(tel.get("containerId",""))
        if not txt.strip() or not cont: continue
        tx,ty,lines,lh=pos(tel,cont,fs)
        for li,l in enumerate(lines):
            svg.append(f'<text x="{px(tx)}" y="{py(ty+li*lh)}" font-size="{fs}" fill="{tel.get("strokeColor","#1e1e1e")}" font-family="Microsoft YaHei,sans-serif">{l.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")}</text>')
    svg.append("</svg>")
    import cairosvg
    cairosvg.svg2png(bytestring="".join(svg).encode(), write_to=out, scale=scale)
    print(f"Rendered: {out}")

if __name__=="__main__":
    usage="Usage: python3 render_excalidraw.py <input.excalidraw> [output.png] [scale=2]"
    if len(sys.argv)<2: print(usage); sys.exit(1)
    render(sys.argv[1], sys.argv[2] if len(sys.argv)>2 else sys.argv[1].replace(".excalidraw",".png"),
           int(sys.argv[3]) if len(sys.argv)>3 else 2)
