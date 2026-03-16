/**
 * FormulaForge Slide Generator — Couture Edition
 * Dynamic color theming: slides adapt to AI-generated brand palette.
 * Reads formula JSON from stdin, produces a premium .pptx
 * Usage: echo '{"formula":...}' | node generate_slides.js output.pptx
 */

const pptxgen = require("pptxgenjs");
const fs = require("fs");

// ── Default Theme (overridden by AI-generated palette) ─────────────────
const DEFAULTS = {
  primary: "4A1942",
  secondary: "A26769",
  accent: "ECE2D0",
  gold: "D4A855",
};

const FONT_HEAD = "Georgia";
const FONT_BODY = "Calibri";
const makeShadow = () => ({ type: "outer", blur: 6, offset: 2, color: "000000", opacity: 0.12 });

// ── Color Utility Functions ────────────────────────────────────────────
function hexToRgb(hex) {
  const h = hex.replace("#", "");
  return { r: parseInt(h.substring(0, 2), 16), g: parseInt(h.substring(2, 4), 16), b: parseInt(h.substring(4, 6), 16) };
}

function darken(hex, amount) {
  const { r, g, b } = hexToRgb(hex);
  const d = (v) => Math.max(0, Math.round(v * (1 - amount))).toString(16).padStart(2, "0");
  return d(r) + d(g) + d(b);
}

function lighten(hex, amount) {
  const { r, g, b } = hexToRgb(hex);
  const l = (v) => Math.min(255, Math.round(v + (255 - v) * amount)).toString(16).padStart(2, "0");
  return l(r) + l(g) + l(b);
}

function dimColor(hex) {
  return darken(hex, 0.4);
}

function getLuma(hex) {
  const c = (hex || "").replace("#", "");
  if (c.length !== 6) return 0;
  const r = parseInt(c.substring(0, 2), 16);
  const g = parseInt(c.substring(2, 4), 16);
  const b = parseInt(c.substring(4, 6), 16);
  return 0.299 * r + 0.587 * g + 0.114 * b;
}

// ── Build Full Theme from 4-Color Palette ──────────────────────────────
function buildTheme(palette) {
  const p = { ...DEFAULTS, ...(palette || {}) };
  const primaryLuma = getLuma(p.primary);
  const safeWhite = primaryLuma > 180 ? darken(p.primary, 0.8) : "FFFFFF";

  return {
    primary: p.primary,
    secondary: p.secondary,
    accent: p.accent,
    gold: p.gold,
    goldDim: dimColor(p.gold),
    white: safeWhite,
    dark: darken(p.primary, 0.45),
    darkCard: lighten(p.primary, 0.15),
    green: "4CAF50",
    red: "E74C3C",
    muted: lighten(p.secondary, 0.35),
    lightBg: lighten(p.accent, 0.4),
    warmGray: lighten(p.accent, 0.2),
    textDark: darken(p.primary, 0.2),
  };
}

// ── Shared Layout Helpers ──────────────────────────────────────────────
const FOOTER_Y = 5.05;
const FOOTER_H = 0.575;

function addFooterBar(slide, pres, C, text) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: FOOTER_Y, w: 10, h: FOOTER_H,
    fill: { color: C.dark },
  });
  slide.addText(text || "FORMULAFORGE", {
    x: 0.7, y: FOOTER_Y + 0.04, w: 3, h: 0.45,
    fontSize: 8, fontFace: FONT_BODY, color: C.gold, bold: true, charSpacing: 3,
  });
  slide.addText("SAMI & VALERIE", {
    x: 6, y: FOOTER_Y + 0.04, w: 3.3, h: 0.45,
    fontSize: 7, fontFace: FONT_BODY, color: C.goldDim, align: "right", charSpacing: 2,
  });
}

function addSlideHeader(slide, pres, C, title, isDark) {
  slide.addText(title, {
    x: 0.7, y: 0.35, w: 8.6, h: 0.6,
    fontSize: 22, fontFace: FONT_HEAD, color: isDark ? C.white : C.primary,
    bold: true, charSpacing: 3, shrinkText: true,
  });
  slide.addShape(pres.shapes.LINE, {
    x: 0.7, y: 1.0, w: 1.8, h: 0,
    line: { color: isDark ? C.gold : C.secondary, width: 2 },
  });
  slide.addShape(pres.shapes.OVAL, {
    x: 2.6, y: 0.95, w: 0.12, h: 0.12,
    fill: { color: isDark ? C.gold : C.secondary },
  });
}

// ── Read JSON from stdin ───────────────────────────────────────────────
let inputData = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => inputData += chunk);
process.stdin.on("end", async () => {
  try {
    const data = JSON.parse(inputData);
    const outPath = process.argv[2] || "FormulaForge_output.pptx";
    await buildPresentation(data, outPath);
    console.log("OK:" + outPath);
  } catch (err) {
    console.error("SLIDE_ERROR:" + err.message);
    process.exit(1);
  }
});

async function buildPresentation(data, outPath) {
  // ── Build dynamic theme from AI palette ──
  const C = buildTheme(data.brand_palette || {});

  const pres = new pptxgen();
  pres.layout = "LAYOUT_16x9";
  pres.author = "FormulaForge";
  pres.title = `FormulaForge - ${data.brand_name || data.user_input || "Formula"}`;
  pres.transition = { type: "fade", speed: "med" };

  const formula = data.formula_v2 && data.formula_v2.solver_status === "Optimal"
    ? data.formula_v2 : data.formula_v1;
  const hasV2 = data.formula_v2 && data.formula_v2.solver_status === "Optimal";
  const explanation = data.explanation_v2 || data.explanation_v1 || "";
  const ingredients = formula ? formula.ingredients || {} : {};
  const sorted = Object.entries(ingredients)
    .filter(([, v]) => v > 0.001)
    .sort((a, b) => b[1] - a[1]);
  const parsedIngs = data.parsed_ingredients || [];
  const canvasImage = data.canvas_image_path || null;
  const brandName = data.brand_name || data.user_input || "COSMETIC FORMULA";
  const brandVision = data.brand_vision || "";

  // ════════════════════════════════════════════════════════════════════
  // SLIDE 1: TITLE
  // ════════════════════════════════════════════════════════════════════
  const s1 = pres.addSlide();
  s1.background = { color: C.primary };

  // Decorative corner accents
  s1.addShape(pres.shapes.LINE, {
    x: 0.5, y: 0.4, w: 0.8, h: 0, line: { color: C.gold, width: 1 },
  });
  s1.addShape(pres.shapes.LINE, {
    x: 0.5, y: 0.4, w: 0, h: 0.6, line: { color: C.gold, width: 1 },
  });

  // Brand title
  s1.addText(brandName.toUpperCase(), {
    x: 0.7, y: 0.8, w: 4.8, h: 1.8,
    fontSize: 28, fontFace: FONT_HEAD, color: C.white, bold: true,
    valign: "bottom", lineSpacingMultiple: 1.05, shrinkText: true,
  });

  // Gold separator
  s1.addShape(pres.shapes.LINE, {
    x: 0.7, y: 2.75, w: 2.5, h: 0, line: { color: C.gold, width: 2 },
  });

  // Brand vision
  s1.addText(brandVision || "Optimized by FormulaForge \u00D7 Nova Technologies", {
    x: 0.7, y: 2.95, w: 4.5, h: 0.6,
    fontSize: 11, fontFace: FONT_BODY, color: C.white, italic: true,
    shrinkText: true, lineSpacingMultiple: 1.2,
  });

  // Date + Powered by
  const today = new Date().toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" });
  s1.addText(today, {
    x: 0.7, y: 3.6, w: 3, h: 0.35,
    fontSize: 9, fontFace: FONT_BODY, color: C.goldDim,
  });
  s1.addText("Powered by Nova Technologies", {
    x: 0.7, y: 3.95, w: 3, h: 0.3,
    fontSize: 7, fontFace: FONT_BODY, color: C.goldDim, charSpacing: 2,
  });

  // Right side: Nova Canvas product image or decorative shapes
  if (canvasImage && fs.existsSync(canvasImage)) {
    s1.addShape(pres.shapes.RECTANGLE, {
      x: 5.4, y: 0.2, w: 4.4, h: 4.6,
      fill: { color: C.dark },
    });
    s1.addImage({
      path: canvasImage, x: 5.5, y: 0.3, w: 4.2, h: 4.4,
      sizing: { type: "contain", w: 4.2, h: 4.4 },
    });
  } else {
    s1.addShape(pres.shapes.OVAL, {
      x: 6.5, y: 1.0, w: 2.5, h: 2.5,
      fill: { color: C.secondary, transparency: 40 },
    });
    s1.addShape(pres.shapes.OVAL, {
      x: 7.5, y: 2.5, w: 1.8, h: 1.8,
      fill: { color: C.gold, transparency: 60 },
    });
    s1.addShape(pres.shapes.OVAL, {
      x: 5.8, y: 2.8, w: 1.2, h: 1.2,
      fill: { color: C.accent, transparency: 50 },
    });
  }

  addFooterBar(s1, pres, C, "FORMULAFORGE");

  // ════════════════════════════════════════════════════════════════════
  // SLIDE 2: FORMULA OVERVIEW (Stats Cards)
  // ════════════════════════════════════════════════════════════════════
  const s2 = pres.addSlide();
  s2.background = { color: C.lightBg };

  addSlideHeader(s2, pres, C, "FORMULA OVERVIEW", false);

  const stats = [
    { label: "INGREDIENTS", value: String(sorted.length), unit: "total" },
    { label: "PERFORMANCE", value: String(formula ? formula.performance_score : 0), unit: "score" },
    { label: "COST", value: "$" + (formula ? formula.total_cost : 0), unit: "/100g" },
    { label: "STATUS", value: formula ? formula.solver_status : "N/A", unit: "" },
  ];

  stats.forEach((stat, i) => {
    const cx = 0.5 + i * 2.35;
    s2.addShape(pres.shapes.RECTANGLE, {
      x: cx, y: 1.3, w: 2.1, h: 3.2,
      fill: { color: C.white }, shadow: makeShadow(),
    });
    s2.addShape(pres.shapes.RECTANGLE, {
      x: cx, y: 1.3, w: 2.1, h: 0.06,
      fill: { color: i === 0 ? C.gold : C.secondary },
    });
    s2.addText(stat.value, {
      x: cx, y: 1.7, w: 2.1, h: 1.2,
      fontSize: 30, fontFace: FONT_HEAD, color: C.primary, bold: true,
      align: "center", valign: "middle", shrinkText: true,
    });
    s2.addText(stat.unit, {
      x: cx, y: 2.8, w: 2.1, h: 0.35,
      fontSize: 11, fontFace: FONT_BODY, color: C.muted, align: "center",
    });
    s2.addShape(pres.shapes.LINE, {
      x: cx + 0.4, y: 3.3, w: 1.3, h: 0,
      line: { color: C.warmGray, width: 0.5 },
    });
    s2.addText(stat.label, {
      x: cx, y: 3.5, w: 2.1, h: 0.4,
      fontSize: 8, fontFace: FONT_BODY, color: C.secondary, bold: true,
      align: "center", charSpacing: 2,
    });
  });

  addFooterBar(s2, pres, C);

  // ════════════════════════════════════════════════════════════════════
  // SLIDE 3: INGREDIENT BREAKDOWN (Bar Chart)
  // ════════════════════════════════════════════════════════════════════
  const s3 = pres.addSlide();
  s3.background = { color: C.lightBg };

  addSlideHeader(s3, pres, C, "INGREDIENT BREAKDOWN", false);

  const chartLabels = sorted.map(([n]) => n.length > 18 ? n.substring(0, 16) + ".." : n);
  const chartValues = sorted.map(([, v]) => Math.round(v * 100) / 100);

  if (chartLabels.length > 0) {
    s3.addChart(pres.charts.BAR, [{
      name: "Percentage", labels: chartLabels, values: chartValues,
    }], {
      x: 0.5, y: 1.2, w: 9, h: 3.6, barDir: "bar",
      chartColors: [C.primary, C.secondary, C.gold, C.green, lighten(C.primary, 0.3), lighten(C.secondary, 0.2), lighten(C.gold, 0.2), "7B9E89", "9B8EC4", "E8B4B8", "6A9BC3", "A8D8B9"],
      showValue: true, dataLabelPosition: "outEnd", dataLabelColor: C.primary,
      catAxisLabelColor: C.textDark, valAxisLabelColor: "888888",
      valGridLine: { color: C.warmGray, size: 0.5 }, catGridLine: { style: "none" },
      chartArea: { fill: { color: C.lightBg } },
      showLegend: false,
    });
  }

  addFooterBar(s3, pres, C);

  // ════════════════════════════════════════════════════════════════════
  // SLIDE 4: TOP INGREDIENTS DEEP DIVE
  // ════════════════════════════════════════════════════════════════════
  const s4 = pres.addSlide();
  s4.background = { color: C.primary };

  addSlideHeader(s4, pres, C, "TOP INGREDIENTS", true);

  const top4 = sorted.slice(0, 4);
  top4.forEach(([name, pct], i) => {
    const cx = 0.4 + i * 2.4;
    const parsed = parsedIngs.find(p => p.name === name) || {};

    s4.addShape(pres.shapes.RECTANGLE, {
      x: cx, y: 1.25, w: 2.15, h: 3.4,
      fill: { color: C.darkCard }, shadow: makeShadow(),
    });
    s4.addShape(pres.shapes.RECTANGLE, {
      x: cx, y: 1.25, w: 2.15, h: 0.06,
      fill: { color: C.gold },
    });

    s4.addText(pct.toFixed(1) + "%", {
      x: cx, y: 1.5, w: 2.15, h: 0.9,
      fontSize: 30, fontFace: FONT_HEAD, color: C.gold, bold: true,
      align: "center", valign: "middle", shrinkText: true,
    });

    s4.addText(name.toUpperCase(), {
      x: cx + 0.1, y: 2.5, w: 1.95, h: 0.65,
      fontSize: 10, fontFace: FONT_BODY, color: C.white, bold: true,
      align: "center", valign: "top", shrinkText: true,
    });

    const cat = parsed.category || "active";
    const catColor = cat === "active" ? C.secondary : cat === "base" ? "7B9E89" : "8E8E8E";
    s4.addShape(pres.shapes.RECTANGLE, {
      x: cx + 0.45, y: 3.3, w: 1.25, h: 0.28,
      fill: { color: catColor },
    });
    s4.addText(cat.toUpperCase(), {
      x: cx + 0.45, y: 3.3, w: 1.25, h: 0.28,
      fontSize: 7, fontFace: FONT_BODY, color: C.white, bold: true,
      align: "center", valign: "middle", charSpacing: 2,
    });

    const eff = parsed.efficacy_score || "N/A";
    s4.addText("Efficacy: " + eff + "/10", {
      x: cx, y: 3.8, w: 2.15, h: 0.3,
      fontSize: 9, fontFace: FONT_BODY, color: C.muted, align: "center",
    });
  });

  addFooterBar(s4, pres, C);

  // ════════════════════════════════════════════════════════════════════
  // SLIDE 5: REGULATORY COMPLIANCE
  // ════════════════════════════════════════════════════════════════════
  const s5 = pres.addSlide();
  s5.background = { color: C.lightBg };

  addSlideHeader(s5, pres, C, "REGULATORY COMPLIANCE", false);

  const regLimits = {
    "retinol": 1.0, "salicylic acid": 2.0, "benzoyl peroxide": 10.0,
    "vitamin c": 20.0, "ascorbic acid": 20.0, "niacinamide": 10.0,
    "glycolic acid": 10.0, "zinc oxide": 25.0, "fragrance": 1.0,
  };

  const regRows = [];
  for (const [name, pct] of sorted) {
    for (const [regName, regMax] of Object.entries(regLimits)) {
      if (name.toLowerCase().includes(regName)) {
        const compliant = pct <= regMax;
        regRows.push([
          { text: name, options: { fontSize: 10, fontFace: FONT_BODY, color: C.textDark } },
          { text: pct.toFixed(2) + "%", options: { fontSize: 10, fontFace: FONT_BODY, color: C.textDark, align: "center" } },
          { text: regMax + "%", options: { fontSize: 10, fontFace: FONT_BODY, color: C.textDark, align: "center" } },
          { text: compliant ? "\u2705 PASS" : "\u274C OVER", options: { fontSize: 10, fontFace: FONT_BODY, color: compliant ? C.green : C.red, align: "center", bold: true } },
        ]);
      }
    }
  }

  if (regRows.length > 0) {
    const header = [
      { text: "INGREDIENT", options: { fontSize: 9, fontFace: FONT_BODY, color: C.white, bold: true, fill: { color: C.primary } } },
      { text: "USED %", options: { fontSize: 9, fontFace: FONT_BODY, color: C.white, bold: true, fill: { color: C.primary }, align: "center" } },
      { text: "REG. CAP", options: { fontSize: 9, fontFace: FONT_BODY, color: C.white, bold: true, fill: { color: C.primary }, align: "center" } },
      { text: "STATUS", options: { fontSize: 9, fontFace: FONT_BODY, color: C.white, bold: true, fill: { color: C.primary }, align: "center" } },
    ];
    s5.addTable([header, ...regRows], {
      x: 0.7, y: 1.3, w: 8.6, colW: [3.2, 1.6, 1.6, 2.2],
      border: { pt: 0.5, color: C.warmGray },
      rowH: 0.38,
    });
  } else {
    s5.addShape(pres.shapes.RECTANGLE, {
      x: 2.5, y: 1.8, w: 5, h: 2.5,
      fill: { color: C.white }, shadow: makeShadow(),
    });
    s5.addShape(pres.shapes.OVAL, {
      x: 4.55, y: 2.0, w: 0.9, h: 0.9,
      fill: { color: C.green, transparency: 20 },
    });
    s5.addText("\u2713", {
      x: 4.55, y: 2.0, w: 0.9, h: 0.9,
      fontSize: 28, color: C.green, align: "center", valign: "middle", bold: true,
    });
    s5.addText("ALL CLEAR", {
      x: 2.5, y: 3.0, w: 5, h: 0.5,
      fontSize: 18, fontFace: FONT_HEAD, color: C.primary, align: "center", bold: true,
    });
    s5.addText("No regulated ingredients detected.\nAll components are within standard safe-use limits.", {
      x: 2.5, y: 3.5, w: 5, h: 0.6,
      fontSize: 10, fontFace: FONT_BODY, color: C.muted, align: "center",
      lineSpacingMultiple: 1.3, shrinkText: true,
    });
  }

  addFooterBar(s5, pres, C);

  // ════════════════════════════════════════════════════════════════════
  // SLIDE 6: INTERACTION MAP
  // ════════════════════════════════════════════════════════════════════
  const s6 = pres.addSlide();
  s6.background = { color: C.primary };

  addSlideHeader(s6, pres, C, "INTERACTION MAP", true);

  const interactions = (formula ? formula.interactions : []) || [];
  const maxInteractions = Math.min(interactions.length, 4);

  if (maxInteractions > 0) {
    const rowH = Math.min(0.85, 3.4 / maxInteractions);
    interactions.slice(0, 4).forEach((inter, i) => {
      const yPos = 1.25 + i * (rowH + 0.1);
      const isConflict = inter.type === "conflict";

      s6.addShape(pres.shapes.RECTANGLE, {
        x: 0.7, y: yPos, w: 8.6, h: rowH,
        fill: { color: isConflict ? darken(C.red, 0.6) : darken(C.green, 0.6) }, shadow: makeShadow(),
      });
      s6.addShape(pres.shapes.RECTANGLE, {
        x: 0.7, y: yPos, w: 0.08, h: rowH,
        fill: { color: isConflict ? C.red : C.green },
      });

      s6.addText((isConflict ? "\u26A0\uFE0F " : "\u2705 ") + inter.a + "  \u00D7  " + inter.b, {
        x: 1.0, y: yPos, w: 4, h: rowH,
        fontSize: 12, fontFace: FONT_BODY, color: C.white, bold: true,
        valign: "middle", shrinkText: true,
      });
      s6.addText(inter.note || "", {
        x: 5.2, y: yPos, w: 3.8, h: rowH,
        fontSize: 9, fontFace: FONT_BODY, color: C.muted, valign: "middle",
        italic: true, shrinkText: true,
      });
    });
  } else {
    s6.addShape(pres.shapes.RECTANGLE, {
      x: 2.5, y: 2.0, w: 5, h: 1.8,
      fill: { color: C.darkCard }, shadow: makeShadow(),
    });
    s6.addText("No known interactions detected.\nAll ingredients are compatible.", {
      x: 2.5, y: 2.2, w: 5, h: 1.4,
      fontSize: 14, fontFace: FONT_BODY, color: C.accent, align: "center",
      valign: "middle", shrinkText: true, lineSpacingMultiple: 1.4,
    });
  }

  addFooterBar(s6, pres, C);

  // ════════════════════════════════════════════════════════════════════
  // SLIDE 7: FORMULA EVOLUTION (v1 vs v2)
  // ════════════════════════════════════════════════════════════════════
  const s7 = pres.addSlide();
  s7.background = { color: C.lightBg };

  addSlideHeader(s7, pres, C, "FORMULA EVOLUTION", false);

  if (hasV2) {
    const v1 = data.formula_v1.ingredients || {};
    const v2 = data.formula_v2.ingredients || {};
    const allNames = [...new Set([...Object.keys(v1), ...Object.keys(v2)])].sort();

    const compHeader = [
      { text: "INGREDIENT", options: { fontSize: 8, fontFace: FONT_BODY, color: C.white, bold: true, fill: { color: C.primary } } },
      { text: "V1 %", options: { fontSize: 8, fontFace: FONT_BODY, color: C.white, bold: true, fill: { color: C.primary }, align: "center" } },
      { text: "V2 %", options: { fontSize: 8, fontFace: FONT_BODY, color: C.white, bold: true, fill: { color: C.primary }, align: "center" } },
      { text: "DELTA", options: { fontSize: 8, fontFace: FONT_BODY, color: C.white, bold: true, fill: { color: C.primary }, align: "center" } },
    ];

    const compRows = allNames
      .filter(n => (v1[n] || 0) > 0.001 || (v2[n] || 0) > 0.001)
      .slice(0, 10)
      .map(name => {
        const p1 = v1[name] || 0, p2 = v2[name] || 0;
        const delta = p2 - p1;
        const dColor = delta > 0.01 ? C.green : delta < -0.01 ? C.red : "888888";
        return [
          { text: name, options: { fontSize: 8, fontFace: FONT_BODY, color: C.textDark } },
          { text: p1 > 0 ? p1.toFixed(2) + "%" : "-", options: { fontSize: 8, fontFace: FONT_BODY, color: "555555", align: "center" } },
          { text: p2 > 0 ? p2.toFixed(2) + "%" : "-", options: { fontSize: 8, fontFace: FONT_BODY, color: "555555", align: "center" } },
          { text: (delta >= 0 ? "+" : "") + delta.toFixed(2) + "%", options: { fontSize: 8, fontFace: FONT_BODY, color: dColor, bold: true, align: "center" } },
        ];
      });

    s7.addTable([compHeader, ...compRows], {
      x: 0.5, y: 1.2, w: 5.5, colW: [2.2, 1.0, 1.0, 1.3],
      border: { pt: 0.5, color: C.warmGray }, rowH: 0.3,
    });

    const scoreDelta = data.formula_v2.performance_score - data.formula_v1.performance_score;
    const costDelta = data.formula_v2.total_cost - data.formula_v1.total_cost;

    s7.addShape(pres.shapes.RECTANGLE, {
      x: 6.5, y: 1.3, w: 3, h: 1.5, fill: { color: C.white }, shadow: makeShadow(),
    });
    s7.addShape(pres.shapes.RECTANGLE, {
      x: 6.5, y: 1.3, w: 3, h: 0.04, fill: { color: scoreDelta >= 0 ? C.green : C.red },
    });
    s7.addText("SCORE CHANGE", {
      x: 6.5, y: 1.4, w: 3, h: 0.3,
      fontSize: 8, fontFace: FONT_BODY, color: C.muted, align: "center", charSpacing: 2,
    });
    s7.addText((scoreDelta >= 0 ? "+" : "") + scoreDelta.toFixed(1), {
      x: 6.5, y: 1.7, w: 3, h: 0.8,
      fontSize: 34, fontFace: FONT_HEAD, color: scoreDelta >= 0 ? C.green : C.red,
      bold: true, align: "center", valign: "middle", shrinkText: true,
    });

    s7.addShape(pres.shapes.RECTANGLE, {
      x: 6.5, y: 3.1, w: 3, h: 1.5, fill: { color: C.white }, shadow: makeShadow(),
    });
    s7.addShape(pres.shapes.RECTANGLE, {
      x: 6.5, y: 3.1, w: 3, h: 0.04, fill: { color: costDelta <= 0 ? C.green : C.red },
    });
    s7.addText("COST CHANGE", {
      x: 6.5, y: 3.2, w: 3, h: 0.3,
      fontSize: 8, fontFace: FONT_BODY, color: C.muted, align: "center", charSpacing: 2,
    });
    s7.addText((costDelta >= 0 ? "+$" : "-$") + Math.abs(costDelta).toFixed(2), {
      x: 6.5, y: 3.5, w: 3, h: 0.8,
      fontSize: 34, fontFace: FONT_HEAD, color: costDelta <= 0 ? C.green : C.red,
      bold: true, align: "center", valign: "middle", shrinkText: true,
    });

  } else {
    s7.addShape(pres.shapes.RECTANGLE, {
      x: 2, y: 1.8, w: 6, h: 2.5, fill: { color: C.white }, shadow: makeShadow(),
    });
    s7.addShape(pres.shapes.RECTANGLE, {
      x: 2, y: 1.8, w: 6, h: 0.04, fill: { color: C.gold },
    });
    s7.addText("OPTIMIZED IN A SINGLE PASS", {
      x: 2, y: 2.1, w: 6, h: 0.6,
      fontSize: 22, fontFace: FONT_HEAD, color: C.primary, bold: true,
      align: "center", shrinkText: true,
    });
    s7.addText("This formula achieved optimal performance on its first optimization.\nRe-run with refinement loops for v1 vs v2 comparison.", {
      x: 2.5, y: 2.8, w: 5, h: 1.0,
      fontSize: 11, fontFace: FONT_BODY, color: C.muted, align: "center",
      shrinkText: true, lineSpacingMultiple: 1.3,
    });
  }

  addFooterBar(s7, pres, C);

  // ════════════════════════════════════════════════════════════════════
  // SLIDE 8: SCIENTIFIC ANALYSIS
  // ════════════════════════════════════════════════════════════════════
  const s8 = pres.addSlide();
  s8.background = { color: C.lightBg };

  addSlideHeader(s8, pres, C, "SCIENTIFIC ANALYSIS", false);

  s8.addShape(pres.shapes.RECTANGLE, {
    x: 0.7, y: 1.2, w: 0.06, h: 3.6, fill: { color: C.secondary },
  });

  let explText = explanation || "No scientific explanation available.";
  explText = explText.replace(/```[\s\S]*?```/g, "").replace(/^\s*[\[{][\s\S]*?[}\]]/gm, "").trim();
  if (explText.length > 1500) explText = explText.substring(0, 1500) + "\u2026";

  s8.addText(explText, {
    x: 1.0, y: 1.2, w: 8.3, h: 3.6,
    fontSize: 10,
    fontFace: FONT_BODY, color: C.textDark, lineSpacingMultiple: 1.3,
    valign: "top",
    shrinkText: true,
  });

  addFooterBar(s8, pres, C);

  // ════════════════════════════════════════════════════════════════════
  // SLIDE 9: CLOSING — LUXURY FINISH
  // ════════════════════════════════════════════════════════════════════
  const s9 = pres.addSlide();
  s9.background = { color: C.primary };

  if (canvasImage && fs.existsSync(canvasImage)) {
    s9.addImage({
      path: canvasImage, x: 0, y: 0, w: 10, h: 5.625, transparency: 88,
      sizing: { type: "cover", w: 10, h: 5.625 },
    });
  }

  s9.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 5.625,
    fill: { color: C.primary, transparency: canvasImage ? 15 : 0 },
  });

  s9.addShape(pres.shapes.LINE, {
    x: 3.5, y: 1.0, w: 3, h: 0, line: { color: C.gold, width: 1 },
  });

  s9.addText(brandName.toUpperCase(), {
    x: 1, y: 1.2, w: 8, h: 1.4,
    fontSize: 34, fontFace: FONT_HEAD, color: C.white, bold: true,
    align: "center", valign: "middle", shrinkText: true,
  });

  s9.addShape(pres.shapes.LINE, {
    x: 3.5, y: 2.7, w: 3, h: 0, line: { color: C.gold, width: 2 },
  });

  s9.addText("Generated by FormulaForge \u00D7 Nova Technologies", {
    x: 1, y: 2.9, w: 8, h: 0.45,
    fontSize: 12, fontFace: FONT_BODY, color: C.accent, align: "center", italic: true,
  });
  s9.addText("From idea to optimized formula in seconds.", {
    x: 1, y: 3.4, w: 8, h: 0.4,
    fontSize: 10, fontFace: FONT_BODY, color: C.muted, align: "center",
  });

  s9.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: FOOTER_Y, w: 10, h: FOOTER_H, fill: { color: C.dark },
  });
  s9.addText("SAMI & VALERIE  \u2502  Nova Technologies", {
    x: 1, y: FOOTER_Y + 0.04, w: 8, h: 0.45,
    fontSize: 9, fontFace: FONT_BODY, color: C.gold, align: "center", charSpacing: 2,
  });

  await pres.writeFile({ fileName: outPath });
}
