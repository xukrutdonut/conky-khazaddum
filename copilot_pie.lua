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

local function draw_donut(cr, cx, cy, R, pct, label, sublabel, clr_used, clr_track)
    local PI    = math.pi
    local lw    = R * 0.30
    local r_arc = R - lw / 2
    local capped = math.max(0, math.min(pct or 0, 100))

    cairo_set_line_width(cr, lw)
    cairo_set_line_cap(cr, CAIRO_LINE_CAP_BUTT)
    local tr, tg, tb, ta = hex_to_rgba(clr_track, 0.25)
    cairo_set_source_rgba(cr, tr, tg, tb, ta)
    cairo_arc(cr, cx, cy, r_arc, 0, 2 * PI)
    cairo_stroke(cr)

    local angle = (capped / 100) * 2 * PI
    if angle > 0.01 then
        local ur, ug, ub, ua = hex_to_rgba(clr_used, 0.90)
        cairo_set_source_rgba(cr, ur, ug, ub, ua)
        cairo_arc(cr, cx, cy, r_arc, -PI / 2, -PI / 2 + angle)
        cairo_stroke(cr)
        local ex = cx + r_arc * math.cos(-PI / 2 + angle)
        local ey = cy + r_arc * math.sin(-PI / 2 + angle)
        cairo_arc(cr, ex, ey, lw / 2 + 1, 0, 2 * PI)
        cairo_fill(cr)
    end

    local pct_txt = (pct ~= nil) and string.format('%.0f%%', capped) or 'N/A'
    draw_text_centered(cr, pct_txt, cx, cy, R * 0.33, true, 1, 1, 1, 0.92)

    local lr, lg, lb = hex_to_rgba(clr_used, 1.0)
    draw_text_centered(cr, label,    cx, cy + R + 18, 13, true,  lr, lg, lb, 0.90)
    draw_text_centered(cr, sublabel, cx, cy + R + 34, 10, false, 0.70, 0.70, 0.70, 0.75)
end

function conky_copilot_pies()
    if conky_window == nil then return end

    local cs = conky_window.cairo_surface
    if cs == nil then return end
    local cr = cairo_create(cs)
    if cr == nil then return end

    local ctx_str   = conky_parse('${execi 5 ~/.config/conky/copilot_context.sh}')
    local quota_str = conky_parse('${execi 300 ~/.config/conky/copilot_quota.sh}')

    local ctx_pct   = tonumber(ctx_str)
    local quota_pct = tonumber(quota_str)

    local ctx_clr = '5af78e'
    if ctx_pct == nil then
        ctx_clr = '888888'
    elseif ctx_pct > 80 then
        ctx_clr = 'ff6e6e'
    elseif ctx_pct > 55 then
        ctx_clr = 'ffb347'
    end

    local quota_clr = '5af78e'
    if quota_pct == nil then
        quota_clr = '888888'
    elseif quota_pct < 20 then
        quota_clr = 'ff6e6e'
    elseif quota_pct < 40 then
        quota_clr = 'ffb347'
    end

    local R  = 82
    local cy = 148
    local cx1 = math.floor(conky_window.width / 4)
    local cx2 = math.floor(conky_window.width * 3 / 4)

    cairo_set_line_width(cr, 1)
    cairo_set_source_rgba(cr, 1, 0.84, 0, 0.20)
    cairo_move_to(cr, conky_window.width / 2, 8)
    cairo_line_to(cr, conky_window.width / 2, cy + R + 52)
    cairo_stroke(cr)

    local ctx_sub = (ctx_pct == nil) and 'sin sesion' or 'sesion activa'
    draw_donut(cr, cx1, cy, R, ctx_pct,   'CONTEXTO', ctx_sub,    ctx_clr,   'ffffff')
    draw_donut(cr, cx2, cy, R, quota_pct, 'CUOTA',    'restante', quota_clr, 'ffffff')

    cairo_destroy(cr)
end
