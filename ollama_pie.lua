require 'cairo'

local function hex_to_rgba(hex, alpha)
    return tonumber(hex:sub(1,2), 16) / 255,
           tonumber(hex:sub(3,4), 16) / 255,
           tonumber(hex:sub(5,6), 16) / 255,
           alpha or 1.0
end

local function draw_text_centered(cr, text, cx, cy, size, bold, r, g, b, a)
    local weight = bold and CAIRO_FONT_WEIGHT_BOLD or CAIRO_FONT_WEIGHT_NORMAL
    cairo_select_font_face(cr, 'DejaVu Sans Mono', CAIRO_FONT_SLANT_NORMAL, weight)
    cairo_set_font_size(cr, size)
    cairo_set_source_rgba(cr, r, g, b, a or 0.9)
    local te = cairo_text_extents_t:create()
    tolua.takeownership(te)
    cairo_text_extents(cr, text, te)
    cairo_move_to(cr, cx - te.width / 2 - te.x_bearing,
                      cy - te.height / 2 - te.y_bearing)
    cairo_show_text(cr, text)
end

local function draw_donut(cr, cx, cy, R, pct, label, clr_used, clr_track)
    local PI     = math.pi
    local lw     = R * 0.30
    local r_arc  = R - lw / 2
    local capped = math.max(0, math.min(pct or 0, 100))

    cairo_set_line_width(cr, lw)
    cairo_set_line_cap(cr, CAIRO_LINE_CAP_BUTT)
    local tr, tg, tb, ta = hex_to_rgba(clr_track, 0.20)
    cairo_set_source_rgba(cr, tr, tg, tb, ta)
    cairo_arc(cr, cx, cy, r_arc, 0, 2 * PI)
    cairo_stroke(cr)

    local angle = (capped / 100) * 2 * PI
    if angle > 0.01 then
        local ur, ug, ub, ua = hex_to_rgba(clr_used, 0.90)
        cairo_set_source_rgba(cr, ur, ug, ub, ua)
        cairo_arc(cr, cx, cy, r_arc, -PI / 2, -PI / 2 + angle)
        cairo_stroke(cr)
    end

    local pct_txt = (pct ~= nil) and string.format('%.0f%%', capped) or 'N/A'
    draw_text_centered(cr, pct_txt, cx, cy, R * 0.35, true, 1, 1, 1, 0.95)

    local lr, lg, lb = hex_to_rgba(clr_used, 1.0)
    draw_text_centered(cr, label, cx, cy + R + 14, 11, true, lr, lg, lb, 0.90)
end

function conky_ollama_pies()
    if conky_window == nil then return end
    local cs = conky_window.cairo_surface
    if cs == nil then return end
    local cr = cairo_create(cs)
    if cr == nil then return end

    local val_str = conky_parse('${execi 15 python3 ~/.config/conky/get_ollama_pcts.py}')
    local p1, p2 = val_str:match('(%d+),(%d+)')
    local d_pct = tonumber(p1) or 85
    local w_pct = tonumber(p2) or 68

    local R  = 46
    local cy = 80
    local w = conky_window.width
    local cx1 = math.floor(w * 1 / 4)
    local cx2 = math.floor(w * 3 / 4)

    draw_donut(cr, cx1, cy, R, d_pct, 'DIARIO',  '5af78e', 'ffffff')
    draw_donut(cr, cx2, cy, R, w_pct, 'SEMANAL', '5eb8ff', 'ffffff')

    cairo_destroy(cr)
end
