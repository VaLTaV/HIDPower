"""Renderizador vetorial 4x supersampled dos ícones em memória (RGBA 64x64)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FG_ACTIVE = (255, 255, 255, 255)
FG_SLEEP = (175, 185, 198, 235)
FG_INACTIVE = (160, 170, 180, 225)
BATTERY_BACKING = (15, 23, 42, 140)
SLEEP_MARK_COLOR = (226, 232, 240, 245)
SLEEP_MARK_HALO = (15, 23, 42, 220)

BAR_GREEN = (34, 197, 94, 255)     # > 20%
BAR_YELLOW = (250, 204, 21, 255)   # 11% a 20%
BAR_RED = (239, 68, 68, 255)       # <= 10%

BAR_SLEEP_GREEN = (74, 150, 108, 185)
BAR_SLEEP_YELLOW = (185, 158, 68, 185)
BAR_SLEEP_RED = (180, 82, 82, 185)

CHARGING_BOLT_FILL = (254, 240, 138, 255)
CHARGING_BOLT_OUTLINE = (15, 23, 42, 235)


def _draw_mouse_symbol(img: Image.Image, fg_color: tuple[int, int, int, int]) -> None:
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((24, 26, 134, 232), radius=54, outline=fg_color, width=16)
    draw.line(((28, 110), (130, 110)), fill=fg_color, width=12)
    draw.rounded_rectangle((71, 48, 87, 94), radius=8, fill=fg_color)


def _draw_gamepad_symbol(img: Image.Image, fg_color: tuple[int, int, int, int]) -> None:
    mask = Image.new("L", img.size, 0)
    mdraw = ImageDraw.Draw(mask)

    mdraw.rounded_rectangle((24, 72, 132, 144), radius=28, fill=255)
    mdraw.line(((40, 108), (28, 178)), fill=255, width=38)
    mdraw.ellipse((9, 159, 47, 197), fill=255)
    mdraw.line(((116, 108), (128, 178)), fill=255, width=38)
    mdraw.ellipse((109, 159, 147, 197), fill=255)

    # Recortes transparentes do D-pad (esquerda) e botões de ação (direita)
    mdraw.rectangle((34, 102, 64, 114), fill=0)
    mdraw.rectangle((43, 93, 55, 123), fill=0)
    mdraw.ellipse((105, 88, 121, 104), fill=0)
    mdraw.ellipse((93, 108, 109, 124), fill=0)

    if fg_color[3] < 255:
        alpha_scale = fg_color[3]
        mask = mask.point(lambda p: (p * alpha_scale) // 255)

    layer = Image.new("RGBA", img.size, fg_color[:3] + (0,))
    layer.putalpha(mask)
    img.alpha_composite(layer)


def _draw_headset_symbol(img: Image.Image, fg_color: tuple[int, int, int, int]) -> None:
    draw = ImageDraw.Draw(img)
    draw.arc((24, 34, 134, 166), start=175, end=365, fill=fg_color, width=16)
    draw.rounded_rectangle((16, 104, 50, 194), radius=14, fill=fg_color)
    draw.rounded_rectangle((108, 104, 142, 194), radius=14, fill=fg_color)
    draw.line(((36, 192), (66, 222), (90, 222)), fill=fg_color, width=12, joint="curve")
    draw.ellipse((83, 214, 99, 230), fill=fg_color)


def _draw_keyboard_symbol(img: Image.Image, fg_color: tuple[int, int, int, int]) -> None:
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((10, 66, 148, 190), radius=16, outline=fg_color, width=14)
    for y in (92, 120):
        for x in (30, 56, 82, 108):
            draw.rounded_rectangle((x, y, x + 18, y + 18), radius=4, fill=fg_color)
    draw.rounded_rectangle((42, 148, 116, 166), radius=5, fill=fg_color)


def _draw_hub_symbol(img: Image.Image, fg_color: tuple[int, int, int, int]) -> None:
    draw = ImageDraw.Draw(img)
    # Ondas 2.4 GHz + corpo compacto de receptor USB
    draw.arc((38, 28, 120, 110), start=215, end=325, fill=fg_color, width=14)
    draw.arc((54, 52, 104, 102), start=215, end=325, fill=fg_color, width=12)
    draw.rounded_rectangle((42, 106, 116, 204), radius=16, outline=fg_color, width=14)
    draw.rounded_rectangle((56, 202, 102, 230), radius=6, fill=fg_color)


_SYMBOL_DRAWERS = {
    "mouse": _draw_mouse_symbol,
    "gamepad": _draw_gamepad_symbol,
    "headset": _draw_headset_symbol,
    "keyboard": _draw_keyboard_symbol,
    "hub": _draw_hub_symbol,
}


def _bar_color_for_pct(percentage: int, sleeping: bool) -> tuple[int, int, int, int]:
    if percentage > 20:
        return BAR_SLEEP_GREEN if sleeping else BAR_GREEN
    if percentage >= 11:
        return BAR_SLEEP_YELLOW if sleeping else BAR_YELLOW
    return BAR_SLEEP_RED if sleeping else BAR_RED


def render_battery_icon(
    icon_kind: str,
    percentage: int | None,
    charging: bool | None = False,
    sleeping: bool = False,
    last_known_percentage: int | None = None,
) -> Image.Image:
    """Gera ícone 64x64 RGBA transparente com silhueta do periférico e barra vertical."""
    canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    is_sleep_state = percentage is None and sleeping
    if percentage is not None:
        fg_color = FG_ACTIVE
    elif is_sleep_state:
        fg_color = FG_SLEEP
    else:
        fg_color = FG_INACTIVE

    symbol_drawer = _SYMBOL_DRAWERS.get(icon_kind, _draw_mouse_symbol)
    symbol_drawer(canvas, fg_color)

    # Polo superior + moldura externa da barra vertical de bateria (lado direito)
    draw.rounded_rectangle((186, 18, 224, 38), radius=6, fill=fg_color)
    draw.rounded_rectangle(
        (164, 36, 246, 236),
        radius=18,
        fill=BATTERY_BACKING,
        outline=fg_color,
        width=14,
    )

    inner_left, inner_top, inner_right, inner_bottom = 180, 52, 230, 220
    inner_h = inner_bottom - inner_top

    if percentage is not None:
        clamped = max(0, min(100, int(percentage)))
        if clamped > 0:
            fill_h = max(20, round(inner_h * clamped / 100))
            draw.rounded_rectangle(
                (inner_left, inner_bottom - fill_h, inner_right, inner_bottom),
                radius=6,
                fill=_bar_color_for_pct(clamped, sleeping=False),
            )

        if charging is True:
            bolt = [
                (212, 92),
                (189, 138),
                (205, 138),
                (198, 178),
                (223, 128),
                (207, 128),
            ]
            draw.polygon(bolt, fill=CHARGING_BOLT_FILL, outline=CHARGING_BOLT_OUTLINE, width=4)
    elif is_sleep_state:
        if last_known_percentage is not None:
            clamped = max(0, min(100, int(last_known_percentage)))
            if clamped > 0:
                fill_h = max(20, round(inner_h * clamped / 100))
                draw.rounded_rectangle(
                    (inner_left, inner_bottom - fill_h, inner_right, inner_bottom),
                    radius=6,
                    fill=_bar_color_for_pct(clamped, sleeping=True),
                )
        else:
            # Traço horizontal indicando standby sem leitura prévia
            draw.line(((186, 136), (224, 136)), fill=fg_color, width=12)

        # Marca "Z" compacta no canto superior esquerdo para sinalizar modo sleep/desligado
        z_pts = ((8, 14), (38, 14), (8, 46), (38, 46))
        draw.line(z_pts, fill=SLEEP_MARK_HALO, width=16, joint="curve")
        draw.line(z_pts, fill=SLEEP_MARK_COLOR, width=9, joint="curve")
    else:
        draw.line(((182, 212), (228, 60)), fill=fg_color, width=12)

    return canvas.resize((64, 64), Image.Resampling.LANCZOS)


def render_hip_emblem(height: int = 44) -> Image.Image:
    """Gera em memória o emblema vetorial 4x supersampled 'H [Bateria-I] P' (RGBA)."""
    base_w, base_h = 460, 220
    canvas = Image.new("RGBA", (base_w, base_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    white = (248, 250, 252, 255)
    dark_bg = (15, 23, 42, 255)
    green_fill = (34, 197, 94, 255)
    green_hi = (74, 222, 128, 255)
    bolt_white = (255, 255, 255, 255)

    # Letra H (esquerda)
    draw.rounded_rectangle((18, 26, 52, 194), radius=8, fill=white)
    draw.rounded_rectangle((102, 26, 136, 194), radius=8, fill=white)
    draw.rounded_rectangle((34, 93, 120, 127), radius=4, fill=white)

    # Letra I estilizada como bateria vertical de celular carregando (centro)
    draw.rounded_rectangle((204, 14, 240, 34), radius=6, fill=white)
    draw.rounded_rectangle(
        (172, 32, 272, 194),
        radius=18,
        fill=dark_bg,
        outline=white,
        width=12,
    )
    # Preenchimento verde vibrante (~85%) + leve brilho superior
    draw.rounded_rectangle((188, 66, 256, 178), radius=8, fill=green_fill)
    draw.rounded_rectangle((192, 68, 252, 80), radius=4, fill=green_hi)
    # Pequeno raio branco no centro
    bolt = [
        (228, 86),
        (205, 124),
        (221, 124),
        (215, 158),
        (240, 118),
        (224, 118),
    ]
    draw.polygon(bolt, fill=bolt_white)

    # Letra P (direita) com máscara L para recorte interno limpo
    p_mask = Image.new("L", (base_w, base_h), 0)
    pm = ImageDraw.Draw(p_mask)
    pm.rounded_rectangle((308, 26, 342, 194), radius=8, fill=255)
    pm.rectangle((324, 26, 376, 128), fill=255)
    pm.rounded_rectangle((326, 26, 424, 128), radius=51, fill=255)
    pm.rectangle((342, 58, 374, 96), fill=0)
    pm.ellipse((354, 58, 392, 96), fill=0)

    p_layer = Image.new("RGBA", (base_w, base_h), white[:3] + (0,))
    p_layer.putalpha(p_mask)
    canvas.alpha_composite(p_layer)

    target_h = max(16, int(height))
    target_w = max(32, round(base_w * target_h / base_h))
    return canvas.resize((target_w, target_h), Image.Resampling.LANCZOS)


def _load_bold_font(size: int, semibold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if semibold:
        candidates = (
            "C:/Windows/Fonts/seguisb.ttf",
            "C:/Windows/Fonts/segoeuib.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/calibrib.ttf",
        )
    else:
        candidates = (
            "C:/Windows/Fonts/seguibl.ttf",
            "C:/Windows/Fonts/segoeuib.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/calibrib.ttf",
        )
    for font_path in candidates:
        try:
            if Path(font_path).exists():
                return ImageFont.truetype(font_path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def render_app_badge_image(size: int = 64) -> Image.Image:
    """Gera em memória o ícone RGBA da janela do aplicativo sem gravar arquivos em disco."""
    badge = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(badge)
    draw.rounded_rectangle(
        (8, 8, 248, 248),
        radius=52,
        fill=(15, 23, 42, 255),
        outline=(51, 65, 85, 255),
        width=8,
    )
    emblem = render_hip_emblem(height=102)
    x0 = (256 - emblem.width) // 2
    y0 = (256 - emblem.height) // 2
    badge.alpha_composite(emblem, (x0, y0))
    return badge.resize((size, size), Image.Resampling.LANCZOS)


def render_github_logo_banner(width: int = 960, height: int = 240) -> Image.Image:
    """Gera banner horizontal PNG do projeto HIDPower com emblema HIP + wordmark."""
    banner = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(banner)
    draw.rounded_rectangle(
        (6, 6, width - 6, height - 6),
        radius=34,
        fill=(15, 23, 42, 255),
        outline=(51, 65, 85, 255),
        width=4,
    )

    emblem = render_hip_emblem(height=128)
    ex = 48
    ey = (height - emblem.height) // 2
    banner.alpha_composite(emblem, (ex, ey))

    div_x = ex + emblem.width + 28
    draw.line(((div_x, 48), (div_x, height - 48)), fill=(51, 65, 85, 255), width=3)

    title_font = _load_bold_font(78, semibold=False)
    sub_font = _load_bold_font(22, semibold=True)

    tx = div_x + 32
    ty = 50
    hid_text = "HID"
    power_text = "Power"
    draw.text((tx, ty), hid_text, font=title_font, fill=(248, 250, 252, 255))
    bbox = draw.textbbox((tx, ty), hid_text, font=title_font)
    draw.text((bbox[2] + 2, ty), power_text, font=title_font, fill=(34, 197, 94, 255))

    draw.text(
        (tx + 2, 152),
        "Wireless Peripheral Battery Monitor for Windows",
        font=sub_font,
        fill=(148, 163, 184, 255),
    )
    return banner


def save_logo_png(output_path: Path) -> Path:
    """Salva o logo oficial do HIDPower exclusivamente em formato PNG."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    banner = render_github_logo_banner()
    banner.save(output_path, format="PNG")
    return output_path


def save_icon_preview(output_path: Path) -> None:
    """Salva folha de contato em barra escura nos tamanhos 64x64 e 20x20 para inspeção."""
    kinds = ["mouse", "gamepad", "headset", "keyboard", "hub"]
    states: list[tuple[int | None, bool, bool, int | None]] = [
        (100, False, False, None),
        (60, False, False, None),
        (20, False, False, None),
        (10, False, False, None),
        (None, False, True, 90),
        (None, False, True, None),
        (None, False, False, None),
        (80, True, False, None),
    ]

    cell_w, cell_h = 108, 112
    sheet = Image.new(
        "RGBA",
        (len(states) * cell_w + 24, len(kinds) * cell_h + 24),
        (67, 94, 90, 255),
    )
    for row, kind in enumerate(kinds):
        for col, (pct, chg, slp, last_pct) in enumerate(states):
            icon64 = render_battery_icon(
                kind,
                pct,
                charging=chg,
                sleeping=slp,
                last_known_percentage=last_pct,
            )
            icon20 = icon64.resize((20, 20), Image.Resampling.LANCZOS)
            x0 = 16 + col * cell_w
            y0 = 16 + row * cell_h
            sheet.alpha_composite(icon64, (x0, y0))
            sheet.alpha_composite(icon20, (x0 + 70, y0 + 22))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)
