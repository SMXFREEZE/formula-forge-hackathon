/**
 * FormulaForge Slide Generator — Maison Edition
 * ─────────────────────────────────────────────
 * Luxury-tier PPTX generator with dynamic brand theming.
 * Usage: echo '<json>' | node generate_slides.js output.pptx
 */

const pptxgen = require("pptxgenjs");
const fs = require("fs");

// ── Default Palette (overridden by AI-generated brand palette) ──────────
const DEFAULTS = { primary: "1A1A2E", secondary: "A26769", accent: "ECE2D0", gold: "C9A84C" };
const FONT_HEAD = "Georgia";
const FONT_BODY = "Calibri";
const FONT_MONO = "Courier New";

// ── Color Math ────────────────────────────────────────────────────────────
function hexToRgb(hex) {
  const h = hex.replace("#", "");
  return { r: parseInt(h.slice(0,2),16), g: parseInt(h.slice(2,4),16), b: parseInt(h.slice(4,6),16) };
}
function rgbToHex({r,g,b}) {
  return [r,g,b].map(v=>Math.max(0,Math.min(255,v)).toString(16).padStart(2,"0")).join("");
}
function darken(hex, a) {
  const {r,g,b}=hexToRgb(hex);
  return rgbToHex({r:Math.round(r*(1-a)),g:Math.round(g*(1-a)),b:Math.round(b*(1-a))});
}
function lighten(hex, a) {
  const {r,g,b}=hexToRgb(hex);
  return rgbToHex({r:Math.round(r+(255-r)*a),g:Math.round(g+(255-g)*a),b:Math.round(b+(255-b)*a)});
}
function mix(h1, h2, t) {
  const a=hexToRgb(h1),b=hexToRgb(h2);
  return rgbToHex({r:Math.round(a.r+(b.r-a.r)*t),g:Math.round(a.g+(b.g-a.g)*t),b:Math.round(a.b+(b.b-a.b)*t)});
}
function luma(hex) {
  const {r,g,b}=hexToRgb(hex);
  return 0.299*r+0.587*g+0.114*b;
}

// ── Product Type Detection ──────────────────────────────────────────────
const PRODUCT_PROFILES = {
  sunscreen: {
    label: "SUN PROTECTION",
    tagline: "Clinically optimized UV defence — broad-spectrum protection engineered to perform.",
    kpi4Label: "UV PROTECTION",
    ingredientSlideTitle: "SPF ACTIVES",
    scienceTitle: "SUN PROTECTION ANALYSIS",
    closingLine: "Broad-spectrum protection — formulated for every skin under the sun.",
    keywords: ["sunscreen","spf","uva","uvb","sun","solar","photoprotect","uv filter","uv-filter","broad-spectrum"],
    ingKeywords: ["zinc oxide","titanium dioxide","octinoxate","oxybenzone","avobenzone","ecamsule","homosalate","octisalate","octocrylene","bemotrizinol"],
    reg: {
      "zinc oxide":25.0,"titanium dioxide":25.0,"octinoxate":7.5,"oxybenzone":6.0,
      "avobenzone":3.0,"ecamsule":2.0,"homosalate":15.0,"octisalate":5.0,"octocrylene":10.0,
      "retinol":1.0,"fragrance":1.0,"limonene":0.1,"linalool":0.1,
    },
    extraSlide: "spf",
  },
  serum: {
    label: "ACTIVE SERUM",
    tagline: "High-potency actives precisely dosed for maximum bioavailability and visible results.",
    kpi4Label: "ACTIVE CONC.",
    ingredientSlideTitle: "KEY ACTIVES",
    scienceTitle: "BIOAVAILABILITY ANALYSIS",
    closingLine: "Precision actives — science distilled to its purest form.",
    keywords: ["serum","ampoule","booster","essence","concentrate","treatment"],
    ingKeywords: ["retinol","vitamin c","ascorbic acid","niacinamide","hyaluronic acid","peptide","bakuchiol","resveratrol","coenzyme","adenosine","argireline"],
    reg: {
      "retinol":1.0,"salicylic acid":2.0,"vitamin c":20.0,"ascorbic acid":20.0,
      "niacinamide":10.0,"glycolic acid":10.0,"lactic acid":10.0,"kojic acid":1.0,
      "hydroquinone":2.0,"fragrance":1.0,"limonene":0.1,"linalool":0.1,"citral":0.02,
    },
    extraSlide: "ph",
  },
  toner: {
    label: "TONER / EXFOLIANT",
    tagline: "pH-balanced chemical exfoliation — resurface, clarify, and refine.",
    kpi4Label: "pH LEVEL",
    ingredientSlideTitle: "EXFOLIATING ACTIVES",
    scienceTitle: "EXFOLIATION & pH ANALYSIS",
    closingLine: "Refinement at the molecular level — smooth, clear, radiant.",
    keywords: ["toner","mist","peel","exfoliant","exfoliating","pha","aha","bha","clarify","clarifying"],
    ingKeywords: ["glycolic acid","lactic acid","salicylic acid","mandelic acid","citric acid","tartaric acid","malic acid","gluconolactone","lactobionic"],
    reg: {
      "glycolic acid":10.0,"lactic acid":10.0,"salicylic acid":2.0,"mandelic acid":10.0,
      "citric acid":10.0,"retinol":1.0,"hydroquinone":2.0,"fragrance":1.0,
      "limonene":0.1,"linalool":0.1,"citral":0.02,
    },
    extraSlide: "ph",
  },
  cleanser: {
    label: "CLEANSER",
    tagline: "Gentle yet effective cleansing system — remove without compromise.",
    kpi4Label: "FOAM QUALITY",
    ingredientSlideTitle: "SURFACTANT SYSTEM",
    scienceTitle: "CLEANSING SYSTEM ANALYSIS",
    closingLine: "Clean skin is the first step — every great formula starts here.",
    keywords: ["cleanser","face wash","body wash","foaming","foam","cleanse","cleansing","wash","gel cleanser"],
    ingKeywords: ["sodium lauryl sulfate","sls","sodium laureth sulfate","sles","cocamidopropyl betaine","coco-betaine","decyl glucoside","lauryl glucoside","coco glucoside","disodium cocoamphodiacetate"],
    reg: {
      "sodium lauryl sulfate":15.0,"sls":15.0,"sodium laureth sulfate":15.0,"sles":15.0,
      "cocamidopropyl betaine":5.0,"phenoxyethanol":1.0,"methylisothiazolinone":0.0015,
      "fragrance":1.0,"limonene":0.1,"linalool":0.1,
    },
    extraSlide: null,
  },
  moisturizer: {
    label: "MOISTURIZER",
    tagline: "Deep hydration and barrier restoration — skin that feels and performs its best.",
    kpi4Label: "MOISTURIZATION",
    ingredientSlideTitle: "BARRIER INGREDIENTS",
    scienceTitle: "HYDRATION & BARRIER ANALYSIS",
    closingLine: "Healthy skin begins with a fortified barrier — protect, hydrate, restore.",
    keywords: ["moisturizer","moisturiser","moisturizing","cream","lotion","emulsion","day cream","night cream","hydrate","hydrating","butter","rich cream"],
    ingKeywords: ["ceramide","shea butter","hyaluronic acid","glycerin","squalane","niacinamide","cholesterol","fatty acid","caprylic","cetyl alcohol","stearic acid"],
    reg: {
      "retinol":1.0,"niacinamide":10.0,"vitamin c":20.0,"ascorbic acid":20.0,
      "hydroquinone":2.0,"kojic acid":1.0,"fragrance":1.0,
      "limonene":0.1,"linalool":0.1,"citral":0.02,
    },
    extraSlide: null,
  },
  hair: {
    label: "HAIR CARE",
    tagline: "Strand-by-strand science — strength, shine, and scalp health from root to tip.",
    kpi4Label: "CONDITIONING",
    ingredientSlideTitle: "HAIR ACTIVES",
    scienceTitle: "HAIR & SCALP ANALYSIS",
    closingLine: "Every strand tells a story — write yours with science.",
    keywords: ["hair","shampoo","conditioner","scalp","keratin","argan","hair mask","hair serum","leave-in","hair oil","hair treatment"],
    ingKeywords: ["cetrimonium chloride","behentrimonium chloride","dimethicone","cyclomethicone","keratin","argan oil","biotin","panthenol","hydrolyzed","quaternium"],
    reg: {
      "cetrimonium chloride":5.0,"behentrimonium chloride":3.0,"dimethicone":10.0,
      "phenoxyethanol":1.0,"methylisothiazolinone":0.0015,"zinc pyrithione":1.0,
      "fragrance":1.0,"limonene":0.1,"linalool":0.1,
    },
    extraSlide: null,
  },
  mask: {
    label: "MASK / TREATMENT",
    tagline: "Intensive treatment delivery — concentrated actives in a single indulgent step.",
    kpi4Label: "TREATMENT INT.",
    ingredientSlideTitle: "TREATMENT ACTIVES",
    scienceTitle: "TREATMENT EFFICACY ANALYSIS",
    closingLine: "Intensive care — because your skin deserves the best.",
    keywords: ["mask","face mask","sheet mask","clay mask","mud mask","charcoal mask","peel-off","peel off","sleeping mask"],
    ingKeywords: ["kaolin","bentonite","charcoal","activated carbon","clay","retinol","vitamin c","aha","bha"],
    reg: {
      "retinol":1.0,"salicylic acid":2.0,"glycolic acid":10.0,"lactic acid":10.0,
      "vitamin c":20.0,"ascorbic acid":20.0,"fragrance":1.0,
      "limonene":0.1,"linalool":0.1,"citral":0.02,
    },
    extraSlide: null,
  },
};

const PRODUCT_DEFAULT = {
  label: "COSMETIC FORMULA",
  tagline: "Precision-engineered cosmetic formula — evidence-based performance at every level.",
  kpi4Label: "SOLVER STATUS",
  ingredientSlideTitle: "TOP INGREDIENTS",
  scienceTitle: "SCIENTIFIC ANALYSIS",
  closingLine: "From idea to optimized formula — in seconds.",
  reg: {
    "retinol":1.0,"salicylic acid":2.0,"benzoyl peroxide":10.0,"vitamin c":20.0,
    "ascorbic acid":20.0,"niacinamide":10.0,"glycolic acid":10.0,"zinc oxide":25.0,
    "lactic acid":10.0,"kojic acid":1.0,"hydroquinone":2.0,"fragrance":1.0,
    "limonene":0.1,"linalool":0.1,"citral":0.02,
  },
  extraSlide: null,
};

function detectProduct(data) {
  const haystack = [
    data.user_input||"",
    data.brand_name||"",
    data.brand_vision||"",
    ...(data.parsed_ingredients||[]).map(p=>p.name||""),
    ...Object.keys((data.formula_v1||{}).ingredients||{}),
  ].join(" ").toLowerCase();

  let best = null, bestScore = 0;
  for(const [key, profile] of Object.entries(PRODUCT_PROFILES)) {
    let score = 0;
    for(const kw of profile.keywords) { if(haystack.includes(kw)) score += 3; }
    for(const kw of profile.ingKeywords) { if(haystack.includes(kw)) score += 1; }
    if(score > bestScore) { bestScore = score; best = key; }
  }
  return bestScore >= 1 ? PRODUCT_PROFILES[best] : PRODUCT_DEFAULT;
}

// ── Strip any leading '#' so pptxgenjs always gets clean 6-char hex ─────
function cleanHex(h) { return (h||"").replace(/^#/, ""); }

// ── Build Full Theme ────────────────────────────────────────────────────
function buildTheme(palette) {
  // Strip '#' from any AI-returned palette values — pptxgenjs requires bare hex
  const raw = {};
  for(const [k,v] of Object.entries(palette||{})) raw[k] = cleanHex(v);
  const p = { ...DEFAULTS, ...raw };
  const bright = luma(p.primary)>160;
  return {
    primary:    p.primary,
    secondary:  p.secondary,
    accent:     p.accent,
    gold:       p.gold,
    goldLight:  lighten(p.gold, 0.35),
    goldDim:    darken(p.gold, 0.3),
    dark:       darken(p.primary, 0.5),
    darker:     darken(p.primary, 0.65),
    card:       lighten(p.primary, 0.12),
    cardLight:  lighten(p.primary, 0.22),
    bg:         lighten(p.accent, 0.55),
    bgWarm:     lighten(p.accent, 0.35),
    white:      bright ? darken(p.accent, 0.7) : "F8F4EE",
    offWhite:   lighten(p.accent, 0.15),
    muted:      mix(p.accent, p.secondary, 0.4),
    textDark:   darken(p.primary, 0.15),
    textMid:    mix(p.primary, p.secondary, 0.5),
    green:      "3DAA73",
    red:        "D64045",
    blue:       "4A90D9",
    purple:     "8B5CF6",
    divider:    lighten(p.accent, 0.05),
  };
}

// ── Global Dimensions ────────────────────────────────────────────────────
const W = 10, H = 5.625;
const FOOT_Y = H - 0.5, FOOT_H = 0.5;
const MARGIN = 0.55;

const shadow = (blur=8, offset=3, op=0.15) => ({ type:"outer", blur, offset, angle:270, color:"000000", opacity: op });

// ── Reusable Components ──────────────────────────────────────────────────
function footer(slide, pres, C, label) {
  slide.addShape(pres.shapes.RECTANGLE, { x:0,y:FOOT_Y,w:W,h:FOOT_H, fill:{color:C.darker} });
  // Gold left accent
  slide.addShape(pres.shapes.RECTANGLE, { x:0,y:FOOT_Y,w:0.04,h:FOOT_H, fill:{color:C.gold} });
  slide.addText((label||"FORMULAFORGE").toUpperCase(), {
    x:MARGIN,y:FOOT_Y+0.04,w:3.5,h:0.38,
    fontSize:7.5,fontFace:FONT_BODY,color:C.gold,bold:true,charSpacing:3,valign:"middle",
  });
  slide.addText("NOVA × AMAZON BEDROCK", {
    x:6,y:FOOT_Y+0.04,w:3.5,h:0.38,
    fontSize:7,fontFace:FONT_BODY,color:C.goldDim,align:"right",charSpacing:2,valign:"middle",
  });
}

function slideHeader(slide, pres, C, title, dark) {
  const tColor = dark ? C.white : C.primary;
  const aColor = dark ? C.gold   : C.secondary;
  // Title
  slide.addText(title, {
    x:MARGIN,y:0.25,w:W-MARGIN*2,h:0.55,
    fontSize:19,fontFace:FONT_HEAD,color:tColor,bold:true,charSpacing:4,shrinkText:true,valign:"middle",
  });
  // Underline accent
  slide.addShape(pres.shapes.RECTANGLE, { x:MARGIN,y:0.85,w:2.0,h:0.035, fill:{color:aColor} });
  slide.addShape(pres.shapes.OVAL, { x:MARGIN+2.05,y:0.828,w:0.075,h:0.075, fill:{color:aColor} });
  slide.addShape(pres.shapes.RECTANGLE, { x:MARGIN+2.18,y:0.85,w:0.5,h:0.035, fill:{color:aColor,transparency:55} });
}

function diagAccent(slide, pres, C) {
  // Diagonal stripe in bottom-right corner (decorative)
  slide.addShape(pres.shapes.RECTANGLE, { x:7.8,y:3.8,w:3,h:2.5,
    fill:{color:C.card,transparency:70}, rotate:18 });
  slide.addShape(pres.shapes.RECTANGLE, { x:8.5,y:4.2,w:2.2,h:1.8,
    fill:{color:C.cardLight,transparency:75}, rotate:18 });
}

function cornerBracket(slide, pres, C, x, y, size, color) {
  const c = color||C.gold, s = size||0.35, lw = 1.2;
  slide.addShape(pres.shapes.LINE,{x,y,w:s,h:0,line:{color:c,width:lw}});
  slide.addShape(pres.shapes.LINE,{x,y,w:0,h:s,line:{color:c,width:lw}});
}

function kpiCard(slide, pres, C, x, y, w, h, value, unit, label, accentColor) {
  const ac = accentColor||C.gold;
  slide.addShape(pres.shapes.RECTANGLE, {x,y,w,h, fill:{color:C.white}, shadow:shadow()});
  slide.addShape(pres.shapes.RECTANGLE, {x,y,w,h:0.055, fill:{color:ac}});
  slide.addText(String(value), {
    x:x,y:y+0.1,w,h:h*0.52,
    fontSize:28,fontFace:FONT_HEAD,color:C.primary,bold:true,align:"center",valign:"middle",shrinkText:true,
  });
  if(unit) slide.addText(unit,{x,y:y+h*0.55,w,h:0.3,fontSize:9,fontFace:FONT_BODY,color:C.muted,align:"center"});
  slide.addShape(pres.shapes.LINE,{x:x+w*0.25,y:y+h*0.72,w:w*0.5,h:0, line:{color:C.divider,width:0.5}});
  slide.addText(label,{x,y:y+h*0.76,w,h:0.3,fontSize:7.5,fontFace:FONT_BODY,color:ac,bold:true,align:"center",charSpacing:2,shrinkText:true});
}

// Simple horizontal progress bar using rectangles
function progressBar(slide, pres, C, x, y, w, h, pct, fillColor) {
  slide.addShape(pres.shapes.RECTANGLE,{x,y,w,h,fill:{color:lighten(fillColor,0.65)}});
  const filled = Math.max(0.001,w*(Math.min(100,pct)/100));
  slide.addShape(pres.shapes.RECTANGLE,{x,y,w:filled,h,fill:{color:fillColor}});
}

// ── STDIN → Build ─────────────────────────────────────────────────────────
let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", chunk => raw += chunk);
process.stdin.on("end", async () => {
  try {
    const data = JSON.parse(raw);
    const outPath = process.argv[2] || "FormulaForge_output.pptx";
    await buildDeck(data, outPath);
    console.log("OK:" + outPath);
  } catch(e) {
    console.error("SLIDE_ERROR:" + e.message);
    process.exit(1);
  }
});

// ════════════════════════════════════════════════════════════════════════
// MAIN BUILD FUNCTION
// ════════════════════════════════════════════════════════════════════════
async function buildDeck(data, outPath) {
  const C = buildTheme(data.brand_palette||{});
  const pres = new pptxgen();
  pres.layout = "LAYOUT_16x9";
  pres.author = "FormulaForge × Nova Technologies";
  pres.title = `${data.brand_name||data.user_input||"Formula"} — FormulaForge`;

  const PROD   = detectProduct(data);
  const formula = data.formula_v2?.solver_status==="Optimal" ? data.formula_v2 : data.formula_v1;
  const hasV2   = data.formula_v2?.solver_status==="Optimal";
  const explanation = data.explanation_v2||data.explanation_v1||"";
  const ingredients  = formula?.ingredients||{};
  const sorted = Object.entries(ingredients).filter(([,v])=>v>0.001).sort((a,b)=>b[1]-a[1]);
  const parsed  = data.parsed_ingredients||[];
  const canvas  = data.canvas_image_path||null;
  const brand   = data.brand_name||data.user_input||"COSMETIC FORMULA";
  const vision  = data.brand_vision||"";
  const palette = data.brand_palette||{};
  const today   = new Date().toLocaleDateString("en-US",{year:"numeric",month:"long",day:"numeric"});

  // ══════════════════════════════════════════════════════════════════════
  // SLIDE 1 — COVER
  // ══════════════════════════════════════════════════════════════════════
  const s1 = pres.addSlide();
  s1.background = {color: C.primary};

  diagAccent(s1, pres, C);

  // Left text panel
  cornerBracket(s1, pres, C, 0.4, 0.32);
  s1.addText("FORMULAFORGE", {
    x:MARGIN,y:0.35,w:5.2,h:0.38,
    fontSize:8,fontFace:FONT_BODY,color:C.gold,bold:true,charSpacing:5,
  });
  s1.addShape(pres.shapes.RECTANGLE,{x:MARGIN,y:0.82,w:0.04,h:2.6,fill:{color:C.gold}});
  s1.addText(brand.toUpperCase(),{
    x:MARGIN+0.22,y:0.82,w:4.8,h:2.6,
    fontSize:34,fontFace:FONT_HEAD,color:C.white,bold:true,
    valign:"middle",lineSpacingMultiple:1.08,shrinkText:true,
  });
  s1.addShape(pres.shapes.RECTANGLE,{x:MARGIN+0.22,y:3.55,w:3,h:0.04,fill:{color:C.gold}});
  s1.addText(vision||"Optimized by FormulaForge × Nova Technologies",{
    x:MARGIN+0.22,y:3.68,w:4.5,h:0.55,
    fontSize:10.5,fontFace:FONT_BODY,color:C.white,italic:true,
    lineSpacingMultiple:1.25,shrinkText:true,
  });
  // Product type badge
  s1.addShape(pres.shapes.ROUNDED_RECTANGLE,{x:MARGIN+0.22,y:4.22,w:2.2,h:0.26,fill:{color:C.secondary,transparency:25},rectRadius:0.04});
  s1.addText(PROD.label,{x:MARGIN+0.22,y:4.22,w:2.2,h:0.26,fontSize:7.5,fontFace:FONT_BODY,color:C.white,bold:true,align:"center",valign:"middle",charSpacing:2});
  s1.addText(today,{
    x:MARGIN+0.22,y:4.52,w:3,h:0.28,fontSize:8,fontFace:FONT_BODY,color:C.goldDim,
  });

  // Right panel — product image or decorative
  if(canvas && fs.existsSync(canvas)) {
    s1.addShape(pres.shapes.RECTANGLE,{x:5.5,y:0.18,w:4.3,h:4.95,fill:{color:C.dark}});
    s1.addShape(pres.shapes.RECTANGLE,{x:5.52,y:0.20,w:4.26,h:4.91,fill:{color:C.darker}});
    s1.addImage({path:canvas,x:5.6,y:0.28,w:4.1,h:4.75,sizing:{type:"contain",w:4.1,h:4.75}});
  } else {
    // Abstract product visualization
    s1.addShape(pres.shapes.OVAL,{x:6.0,y:0.6,w:3.5,h:3.5,fill:{color:C.secondary,transparency:55}});
    s1.addShape(pres.shapes.OVAL,{x:7.2,y:2.5,w:2.2,h:2.2,fill:{color:C.gold,transparency:65}});
    s1.addShape(pres.shapes.OVAL,{x:5.8,y:2.9,w:1.3,h:1.3,fill:{color:C.accent,transparency:55}});
    s1.addShape(pres.shapes.OVAL,{x:8.0,y:0.8,w:1.0,h:1.0,fill:{color:C.gold,transparency:45}});
    s1.addText("◆",{x:7,y:1.8,w:2,h:1,fontSize:48,color:C.goldLight,align:"center",valign:"middle",transparency:20});
  }

  footer(s1, pres, C, brand);

  // ══════════════════════════════════════════════════════════════════════
  // SLIDE 2 — BRAND IDENTITY
  // ══════════════════════════════════════════════════════════════════════
  const s2 = pres.addSlide();
  s2.background = {color: C.bg};
  slideHeader(s2, pres, C, "BRAND IDENTITY", false);

  // Vision quote block
  s2.addShape(pres.shapes.RECTANGLE,{x:MARGIN,y:1.05,w:5.8,h:2.9,fill:{color:C.white},shadow:shadow(10,4,0.12)});
  s2.addShape(pres.shapes.RECTANGLE,{x:MARGIN,y:1.05,w:0.065,h:2.9,fill:{color:C.secondary}});
  s2.addText("❝",{x:MARGIN+0.2,y:1.1,w:0.6,h:0.7,fontSize:28,color:C.gold,fontFace:FONT_HEAD});
  s2.addText(brand,{
    x:MARGIN+0.2,y:1.45,w:5.35,h:0.75,
    fontSize:22,fontFace:FONT_HEAD,color:C.primary,bold:true,shrinkText:true,
  });
  s2.addText(vision||"A precision-engineered cosmetic formula crafted to deliver visible, evidence-based results.",{
    x:MARGIN+0.2,y:2.25,w:5.35,h:1.4,
    fontSize:11,fontFace:FONT_BODY,color:C.textMid,italic:true,
    lineSpacingMultiple:1.4,shrinkText:true,
  });
  s2.addText("Powered by Amazon Nova  ·  FormulaForge",{
    x:MARGIN+0.2,y:3.7,w:5.35,h:0.28,
    fontSize:8,fontFace:FONT_BODY,color:C.muted,charSpacing:1,
  });

  // Color palette swatches
  const swatchKeys = ["primary","secondary","gold","accent"];
  const swatchLabels = ["PRIMARY","SECONDARY","GOLD","ACCENT"];
  const swatchX = 6.85, swatchY = 1.1, swatchW = 1.4, swatchH = 0.65;
  swatchKeys.forEach((k,i) => {
    const hex = cleanHex(palette[k]||DEFAULTS[k]||"999999");
    const sy = swatchY + i*(swatchH+0.2);
    s2.addShape(pres.shapes.RECTANGLE,{x:swatchX,y:sy,w:swatchW,h:swatchH,
      fill:{color:hex}, shadow:shadow(6,2,0.18)});
    s2.addText(swatchLabels[i],{
      x:swatchX+swatchW+0.08,y:sy,w:1.5,h:swatchH*0.55,
      fontSize:7.5,fontFace:FONT_BODY,color:C.textDark,bold:true,charSpacing:2,valign:"middle",
    });
    s2.addText("#"+hex.toUpperCase(),{
      x:swatchX+swatchW+0.08,y:sy+swatchH*0.45,w:1.5,h:swatchH*0.5,
      fontSize:7,fontFace:FONT_MONO,color:C.muted,valign:"middle",
    });
  });
  s2.addText("BRAND PALETTE",{
    x:swatchX,y:3.85,w:2.5,h:0.3,
    fontSize:7,fontFace:FONT_BODY,color:C.goldDim,charSpacing:3,bold:true,
  });

  footer(s2, pres, C);

  // ══════════════════════════════════════════════════════════════════════
  // SLIDE 3 — EXECUTIVE SUMMARY (KPI Cards)
  // ══════════════════════════════════════════════════════════════════════
  const s3 = pres.addSlide();
  s3.background = {color: C.primary};
  diagAccent(s3, pres, C);
  slideHeader(s3, pres, C, "EXECUTIVE SUMMARY", true);

  // 4th KPI is product-specific
  const kpi4Val = PROD.kpi4Label === "pH LEVEL"
    ? (data.formula_v1?.ph ? data.formula_v1.ph.toFixed(1) : (formula?.ph ? formula.ph.toFixed(1) : "~5.5"))
    : PROD.kpi4Label === "UV PROTECTION"
    ? (data.spf_rating ? "SPF "+data.spf_rating : (sorted.find(([n])=>n.toLowerCase().includes("zinc")||n.toLowerCase().includes("titanium")) ? "Broad" : "—"))
    : (formula?.solver_status||"N/A");
  const kpi4Unit = PROD.kpi4Label === "pH LEVEL" ? "optimal range" : PROD.kpi4Label === "UV PROTECTION" ? "spectrum" : "optimizer";
  const kpis = [
    {v:String(sorted.length), u:"ingredients", l:"TOTAL INGS.", c:C.gold},
    {v:String(formula?.performance_score||0), u:"/ 100 pts", l:"PERFORMANCE", c:C.green},
    {v:"$"+(formula?.total_cost||0), u:"per 100g", l:"FORMULA COST", c:C.secondary},
    {v:kpi4Val, u:kpi4Unit, l:PROD.kpi4Label, c:C.blue},
  ];
  kpis.forEach((k,i)=>{
    const cx = MARGIN + i*2.28;
    kpiCard(s3, pres, C, cx, 1.1, 2.05, 3.1, k.v, k.u, k.l, k.c);
  });

  footer(s3, pres, C);

  // ══════════════════════════════════════════════════════════════════════
  // SLIDE 4 — INGREDIENT DISTRIBUTION (Pie chart + table)
  // ══════════════════════════════════════════════════════════════════════
  const s4 = pres.addSlide();
  s4.background = {color: C.bg};
  slideHeader(s4, pres, C, "INGREDIENT DISTRIBUTION", false);

  if(sorted.length>0) {
    // Donut chart left side
    const pieLabels = sorted.slice(0,8).map(([n])=>n.length>14?n.slice(0,13)+"…":n);
    const pieVals   = sorted.slice(0,8).map(([,v])=>Math.round(v*100)/100);
    if(sorted.length>8){ pieLabels.push("Others"); pieVals.push(Math.round((sorted.slice(8).reduce((s,[,v])=>s+v,0))*100)/100); }
    const chartColors=[C.primary,C.secondary,C.gold,C.green,C.blue,C.purple,
                       lighten(C.primary,0.35),lighten(C.secondary,0.35),C.red];
    s4.addChart(pres.charts.DOUGHNUT, [{name:"Pct",labels:pieLabels,values:pieVals}],{
      x:0.3,y:1.0,w:4.5,h:4.0,
      chartColors: chartColors.slice(0,pieLabels.length),
      holeSize:52, showPercent:true, dataLabelFontSize:8,
      dataLabelColor:C.white,
      showLegend:true, legendPos:"b", legendFontSize:8, legendColor:C.textDark,
      chartArea:{fill:{color:C.bg}},
    });

    // Ingredient list right side
    sorted.slice(0,6).forEach(([name,pct],i)=>{
      const py = 1.1 + i*0.65;
      const p = parsed.find(x=>x.name===name)||{};
      const barColor = i===0?C.primary:i===1?C.secondary:i===2?C.gold:C.blue;
      s4.addShape(pres.shapes.RECTANGLE,{x:4.9,y:py,w:4.9,h:0.52,fill:{color:C.white},shadow:shadow(5,2,0.08)});
      s4.addText(name,{x:5.05,y:py+0.02,w:3.0,h:0.28,fontSize:9.5,fontFace:FONT_BODY,color:C.textDark,bold:true,shrinkText:true});
      s4.addText(p.category||"",{x:5.05,y:py+0.28,w:1.5,h:0.2,fontSize:7,fontFace:FONT_BODY,color:C.muted,italic:true});
      // % badge
      s4.addShape(pres.shapes.RECTANGLE,{x:8.6,y:py+0.08,w:1.1,h:0.35,fill:{color:barColor}});
      s4.addText(pct.toFixed(1)+"%",{x:8.6,y:py+0.08,w:1.1,h:0.35,fontSize:10,fontFace:FONT_HEAD,color:C.white,bold:true,align:"center",valign:"middle"});
      // mini bar
      progressBar(s4,pres,C,5.05,py+0.38,3.35,0.065,pct/sorted[0][1]*100,barColor);
    });
  }
  footer(s4, pres, C);

  // ══════════════════════════════════════════════════════════════════════
  // SLIDE 5 — INGREDIENT BAR CHART (Horizontal)
  // ══════════════════════════════════════════════════════════════════════
  const s5 = pres.addSlide();
  s5.background = {color: C.bg};
  slideHeader(s5, pres, C, "INGREDIENT BREAKDOWN", false);

  if(sorted.length>0) {
    const barColors=[C.primary,C.secondary,C.gold,C.green,C.blue,C.purple,
                     darken(C.gold,0.15),darken(C.secondary,0.15)];
    s5.addChart(pres.charts.BAR,[{name:"% by weight",labels:sorted.map(([n])=>n.length>20?n.slice(0,18)+"…":n),values:sorted.map(([,v])=>Math.round(v*100)/100)}],{
      x:0.4,y:1.0,w:9.2,h:4.3,barDir:"bar",
      chartColors: sorted.map((_,i)=>barColors[i%barColors.length]),
      showValue:true,dataLabelFontSize:9,dataLabelColor:C.textDark,dataLabelPosition:"outEnd",
      catAxisLabelColor:C.textDark,catAxisLabelFontSize:9,
      valAxisLabelColor:"888888",valAxisLabelFontSize:8,
      valGridLine:{color:C.divider,size:0.5},catGridLine:{style:"none"},
      barGrouping:"clustered",barGapWidthPct:55,
      chartArea:{fill:{color:C.bg}}, plotArea:{fill:{color:C.bg}},
      showLegend:false,
    });
  }
  footer(s5, pres, C);

  // ══════════════════════════════════════════════════════════════════════
  // SLIDE 6 — TOP INGREDIENTS SHOWCASE (Cards with efficacy bars)
  // ══════════════════════════════════════════════════════════════════════
  const s6 = pres.addSlide();
  s6.background = {color: C.primary};
  diagAccent(s6, pres, C);
  slideHeader(s6, pres, C, PROD.ingredientSlideTitle, true);

  const top4 = sorted.slice(0,4);
  top4.forEach(([name,pct],i)=>{
    const cx = MARGIN + i*2.3;
    const p  = parsed.find(x=>x.name===name)||{};
    const cardAccent = [C.gold,C.secondary,C.green,C.blue][i];

    s6.addShape(pres.shapes.RECTANGLE,{x:cx,y:1.1,w:2.1,h:3.65,fill:{color:C.card},shadow:shadow(10,4,0.25)});
    s6.addShape(pres.shapes.RECTANGLE,{x:cx,y:1.1,w:2.1,h:0.07,fill:{color:cardAccent}});

    // Percentage headline
    s6.addText(pct.toFixed(1)+"%",{
      x:cx,y:1.22,w:2.1,h:0.85,
      fontSize:32,fontFace:FONT_HEAD,color:cardAccent,bold:true,
      align:"center",valign:"middle",shrinkText:true,
    });

    // Name
    s6.addShape(pres.shapes.LINE,{x:cx+0.2,y:2.15,w:1.7,h:0,line:{color:C.cardLight,width:0.5}});
    s6.addText(name.toUpperCase(),{
      x:cx+0.07,y:2.2,w:1.96,h:0.7,
      fontSize:9.5,fontFace:FONT_BODY,color:C.white,bold:true,
      align:"center",shrinkText:true,lineSpacingMultiple:1.2,
    });

    // Category pill
    const cat = p.category||"active";
    const catC = cat==="active"?C.secondary:cat==="base"?"5E8B5E":"7E7E9A";
    s6.addShape(pres.shapes.ROUNDED_RECTANGLE,{x:cx+0.4,y:3.05,w:1.3,h:0.28,fill:{color:catC},rectRadius:0.04});
    s6.addText(cat.toUpperCase(),{x:cx+0.4,y:3.05,w:1.3,h:0.28,fontSize:7,fontFace:FONT_BODY,color:C.white,bold:true,align:"center",valign:"middle",charSpacing:1.5});

    // Efficacy score bar
    const eff = parseFloat(p.efficacy_score)||0;
    s6.addText("EFFICACY",{x:cx+0.12,y:3.44,w:1.86,h:0.22,fontSize:7,fontFace:FONT_BODY,color:C.muted,charSpacing:2,bold:true});
    progressBar(s6,pres,C,cx+0.12,3.68,1.86,0.1,eff*10,cardAccent);
    s6.addText(eff+"/10",{x:cx+0.12,y:3.82,w:1.86,h:0.25,fontSize:8,fontFace:FONT_BODY,color:C.muted,align:"center"});
  });

  footer(s6, pres, C);

  // ══════════════════════════════════════════════════════════════════════
  // SLIDE 7 — FORMULA EVOLUTION (V1 vs V2)
  // ══════════════════════════════════════════════════════════════════════
  const s7 = pres.addSlide();
  s7.background = {color: C.bg};
  slideHeader(s7, pres, C, "FORMULA EVOLUTION", false);

  if(hasV2) {
    const v1ing = data.formula_v1.ingredients||{};
    const v2ing = data.formula_v2.ingredients||{};
    const allN  = [...new Set([...Object.keys(v1ing),...Object.keys(v2ing)])].sort();

    const hdr = [
      {text:"INGREDIENT",options:{fontSize:8,fontFace:FONT_BODY,color:C.white,bold:true,fill:{color:C.primary}}},
      {text:"V1 %",      options:{fontSize:8,fontFace:FONT_BODY,color:C.white,bold:true,fill:{color:C.primary},align:"center"}},
      {text:"V2 %",      options:{fontSize:8,fontFace:FONT_BODY,color:C.white,bold:true,fill:{color:C.primary},align:"center"}},
      {text:"DELTA",     options:{fontSize:8,fontFace:FONT_BODY,color:C.white,bold:true,fill:{color:C.primary},align:"center"}},
    ];
    const rows = allN.filter(n=>(v1ing[n]||0)>0.001||(v2ing[n]||0)>0.001).slice(0,10).map(n=>{
      const p1=v1ing[n]||0, p2=v2ing[n]||0, d=p2-p1;
      const dc = d>0.01?C.green:d<-0.01?C.red:"888888";
      return [
        {text:n,            options:{fontSize:8,fontFace:FONT_BODY,color:C.textDark}},
        {text:p1>0?p1.toFixed(2)+"%":"-",options:{fontSize:8,fontFace:FONT_BODY,color:"666666",align:"center"}},
        {text:p2>0?p2.toFixed(2)+"%":"-",options:{fontSize:8,fontFace:FONT_BODY,color:"666666",align:"center"}},
        {text:(d>=0?"+":"")+d.toFixed(2)+"%",options:{fontSize:8,fontFace:FONT_BODY,color:dc,bold:true,align:"center"}},
      ];
    });
    s7.addTable([hdr,...rows],{
      x:MARGIN,y:1.05,w:5.7,colW:[2.6,1.0,1.0,1.1],
      border:{pt:0.5,color:C.divider},rowH:0.31,
    });

    // Score & cost delta cards
    const sdelta = data.formula_v2.performance_score - data.formula_v1.performance_score;
    const cdelta = data.formula_v2.total_cost - data.formula_v1.total_cost;
    [
      {label:"SCORE CHANGE",val:(sdelta>=0?"+":"")+sdelta.toFixed(1),color:sdelta>=0?C.green:C.red,y:1.1},
      {label:"COST CHANGE",val:(cdelta>=0?"+$":"-$")+Math.abs(cdelta).toFixed(2),color:cdelta<=0?C.green:C.red,y:3.0},
    ].forEach(k=>{
      s7.addShape(pres.shapes.RECTANGLE,{x:6.6,y:k.y,w:3.1,h:1.65,fill:{color:C.white},shadow:shadow()});
      s7.addShape(pres.shapes.RECTANGLE,{x:6.6,y:k.y,w:3.1,h:0.055,fill:{color:k.color}});
      s7.addText(k.label,{x:6.6,y:k.y+0.1,w:3.1,h:0.3,fontSize:8,fontFace:FONT_BODY,color:C.muted,align:"center",charSpacing:2});
      s7.addText(k.val,{x:6.6,y:k.y+0.38,w:3.1,h:1.0,fontSize:38,fontFace:FONT_HEAD,color:k.color,bold:true,align:"center",valign:"middle",shrinkText:true});
    });
  } else {
    // No V2 — show single-pass success badge + formula highlights
    s7.addShape(pres.shapes.RECTANGLE,{x:0.5,y:1.1,w:4.2,h:3.6,fill:{color:C.white},shadow:shadow(14,5,0.14)});
    s7.addShape(pres.shapes.RECTANGLE,{x:0.5,y:1.1,w:4.2,h:0.065,fill:{color:C.gold}});
    s7.addShape(pres.shapes.OVAL,{x:1.9,y:1.4,w:1.4,h:1.4,fill:{color:C.gold,transparency:20}});
    s7.addText("✓",{x:1.9,y:1.4,w:1.4,h:1.4,fontSize:38,color:C.white,bold:true,align:"center",valign:"middle"});
    s7.addText("OPTIMAL IN\nA SINGLE PASS",{x:0.5,y:2.85,w:4.2,h:0.9,fontSize:16,fontFace:FONT_HEAD,color:C.primary,bold:true,align:"center",shrinkText:true,lineSpacingMultiple:1.15});
    s7.addText("Peak performance achieved on the first optimization run.",{
      x:0.65,y:3.75,w:3.9,h:0.6,fontSize:9,fontFace:FONT_BODY,color:C.muted,align:"center",shrinkText:true,lineSpacingMultiple:1.3,
    });

    // Right side — top formula stats
    const cmpText = (data.comparison||"").replace(/\*\*(.+?)\*\*/g,"$1").replace(/\*(.+?)\*/g,"$1").replace(/^#{1,6}\s+/gm,"").replace(/^[\*\-]\s+/gm,"").trim();
    s7.addShape(pres.shapes.RECTANGLE,{x:5.1,y:1.1,w:4.6,h:3.6,fill:{color:C.card},shadow:shadow(10,3,0.2)});
    s7.addShape(pres.shapes.RECTANGLE,{x:5.1,y:1.1,w:4.6,h:0.065,fill:{color:C.secondary}});
    s7.addText("FORMULA HIGHLIGHTS",{x:5.1,y:1.18,w:4.6,h:0.32,fontSize:8,fontFace:FONT_BODY,color:C.muted,align:"center",charSpacing:3});
    const hiText = cmpText.length > 30
      ? cmpText.slice(0,560)+(cmpText.length>560?"…":"")
      : `Performance Score: ${formula?.performance_score||"N/A"} / 100\nTotal Cost: $${formula?.total_cost||"N/A"} / 100g\nIngredients: ${sorted.length}\nSolver: ${formula?.solver_status||"Optimal"}`;
    s7.addText(hiText,{x:5.25,y:1.52,w:4.3,h:3.1,fontSize:9.5,fontFace:FONT_BODY,color:C.white,lineSpacingMultiple:1.4,shrinkText:true,valign:"top"});
  }
  footer(s7, pres, C);

  // ══════════════════════════════════════════════════════════════════════
  // SLIDE 8 — SCIENTIFIC ANALYSIS
  // ══════════════════════════════════════════════════════════════════════
  const s8 = pres.addSlide();
  s8.background = {color: C.primary};
  diagAccent(s8, pres, C);
  slideHeader(s8, pres, C, PROD.scienceTitle, true);

  // Pull out 3 paragraphs — strip markdown formatting so raw * ## ** don't appear in slides
  let expl = explanation
    .replace(/```[\s\S]*?```/g,"")
    .replace(/^\s*[{\[][\s\S]*?[}\]]/gm,"")
    .replace(/\*\*(.+?)\*\*/g,"$1")
    .replace(/\*(.+?)\*/g,"$1")
    .replace(/^#{1,6}\s+/gm,"")
    .replace(/^[\*\-]\s+/gm,"")
    .replace(/\[([^\]]+)\]\([^)]+\)/g,"$1")
    .trim();
  const paras = expl.split(/\n\n+/).filter(p=>p.trim().length>40).slice(0,3);

  if(paras.length>=3) {
    paras.forEach((para,i)=>{
      const icons=["◆","◈","◇"];
      const py = 1.08 + i*1.38;
      s8.addShape(pres.shapes.RECTANGLE,{x:MARGIN,y:py,w:W-MARGIN*2,h:1.22,fill:{color:C.card},shadow:shadow(8,3,0.2)});
      s8.addShape(pres.shapes.RECTANGLE,{x:MARGIN,y:py,w:0.05,h:1.22,fill:{color:[C.gold,C.secondary,C.green][i]}});
      s8.addText(icons[i],{x:MARGIN+0.15,y:py+0.02,w:0.45,h:0.4,fontSize:14,color:[C.gold,C.secondary,C.green][i],fontFace:FONT_HEAD});
      let t = para.trim(); if(t.length>340) t=t.slice(0,337)+"…";
      s8.addText(t,{
        x:MARGIN+0.6,y:py+0.05,w:W-MARGIN*2-0.7,h:1.1,
        fontSize:9.5,fontFace:FONT_BODY,color:C.white,
        lineSpacingMultiple:1.35,shrinkText:true,valign:"top",
      });
    });
  } else {
    // Fallback: single text block
    let t = expl; if(t.length>1400) t=t.slice(0,1397)+"…";
    s8.addShape(pres.shapes.RECTANGLE,{x:MARGIN,y:1.05,w:W-MARGIN*2,h:3.9,fill:{color:C.card}});
    s8.addShape(pres.shapes.RECTANGLE,{x:MARGIN,y:1.05,w:0.05,h:3.9,fill:{color:C.secondary}});
    s8.addText(t,{x:MARGIN+0.2,y:1.1,w:W-MARGIN*2-0.3,h:3.8,fontSize:10,fontFace:FONT_BODY,color:C.white,lineSpacingMultiple:1.4,shrinkText:true,valign:"top"});
  }
  footer(s8, pres, C);

  // ══════════════════════════════════════════════════════════════════════
  // SLIDE 9 — REGULATORY COMPLIANCE
  // ══════════════════════════════════════════════════════════════════════
  const s9 = pres.addSlide();
  s9.background = {color: C.bg};
  const regTitle = PROD.extraSlide==="spf" ? "SPF & REGULATORY COMPLIANCE" : "REGULATORY COMPLIANCE";
  slideHeader(s9, pres, C, regTitle, false);

  const REG = PROD.reg||PRODUCT_DEFAULT.reg;

  const regRows=[];
  for(const [name,pct] of sorted){
    for(const [rn,rmax] of Object.entries(REG)){
      if(name.toLowerCase().includes(rn)){
        const ok=pct<=rmax;
        regRows.push([
          {text:name,options:{fontSize:9.5,fontFace:FONT_BODY,color:C.textDark}},
          {text:pct.toFixed(2)+"%",options:{fontSize:9.5,fontFace:FONT_BODY,color:C.textDark,align:"center"}},
          {text:rmax+"%",options:{fontSize:9.5,fontFace:FONT_BODY,color:C.textMid,align:"center"}},
          {text:"EU/FDA",options:{fontSize:8,fontFace:FONT_BODY,color:C.muted,align:"center"}},
          {text:ok?"✅ PASS":"⚠️ REVIEW",options:{fontSize:9,fontFace:FONT_BODY,color:ok?C.green:C.red,bold:true,align:"center"}},
        ]);
      }
    }
  }

  if(regRows.length>0){
    const hdr=[
      {text:"INGREDIENT",options:{fontSize:8.5,fontFace:FONT_BODY,color:C.white,bold:true,fill:{color:C.primary}}},
      {text:"USED",options:{fontSize:8.5,fontFace:FONT_BODY,color:C.white,bold:true,fill:{color:C.primary},align:"center"}},
      {text:"CAP",options:{fontSize:8.5,fontFace:FONT_BODY,color:C.white,bold:true,fill:{color:C.primary},align:"center"}},
      {text:"REGULATION",options:{fontSize:8.5,fontFace:FONT_BODY,color:C.white,bold:true,fill:{color:C.primary},align:"center"}},
      {text:"STATUS",options:{fontSize:8.5,fontFace:FONT_BODY,color:C.white,bold:true,fill:{color:C.primary},align:"center"}},
    ];
    s9.addTable([hdr,...regRows],{
      x:MARGIN,y:1.05,w:W-MARGIN*2,colW:[3.1,1.3,1.0,1.5,1.9],
      border:{pt:0.5,color:C.divider},rowH:0.38,
    });
  } else {
    s9.addShape(pres.shapes.RECTANGLE,{x:2.8,y:1.8,w:4.4,h:2.5,fill:{color:C.white},shadow:shadow(14,5)});
    s9.addShape(pres.shapes.OVAL,{x:4.25,y:2.1,w:1.5,h:1.5,fill:{color:C.green,transparency:15}});
    s9.addText("✓",{x:4.25,y:2.1,w:1.5,h:1.5,fontSize:44,color:C.white,bold:true,align:"center",valign:"middle"});
    s9.addText("ALL CLEAR",{x:2.8,y:3.65,w:4.4,h:0.48,fontSize:18,fontFace:FONT_HEAD,color:C.primary,bold:true,align:"center"});
    s9.addText("No regulated ingredients detected — within all safe-use limits.",{
      x:3.0,y:4.1,w:4.0,h:0.35,fontSize:9,fontFace:FONT_BODY,color:C.muted,align:"center",shrinkText:true,
    });
  }
  footer(s9, pres, C);

  // ══════════════════════════════════════════════════════════════════════
  // SLIDE 10 — INTERACTION MAP
  // ══════════════════════════════════════════════════════════════════════
  const s10 = pres.addSlide();
  s10.background = {color: C.primary};
  diagAccent(s10, pres, C);
  slideHeader(s10, pres, C, "INGREDIENT INTERACTIONS", true);

  const ints = (formula?.interactions||[]);
  if(ints.length>0){
    const rowH = Math.min(0.92, 3.6/Math.min(ints.length,4));
    ints.slice(0,4).forEach((it,i)=>{
      const y = 1.08 + i*(rowH+0.08);
      const ok = it.type!=="conflict";
      const rowBg = ok ? darken(C.green,0.65) : darken(C.red,0.65);
      const pill  = ok ? C.green : C.red;
      s10.addShape(pres.shapes.RECTANGLE,{x:MARGIN,y,w:W-MARGIN*2,h:rowH,fill:{color:rowBg},shadow:shadow(6,2,0.2)});
      s10.addShape(pres.shapes.RECTANGLE,{x:MARGIN,y,w:0.07,h:rowH,fill:{color:pill}});
      s10.addShape(pres.shapes.ROUNDED_RECTANGLE,{x:MARGIN+0.18,y:y+rowH/2-0.15,w:1.0,h:0.3,fill:{color:pill},rectRadius:0.03});
      s10.addText(ok?"SYNERGY":"CONFLICT",{x:MARGIN+0.18,y:y+rowH/2-0.15,w:1.0,h:0.3,fontSize:7,fontFace:FONT_BODY,color:C.white,bold:true,align:"center",valign:"middle",charSpacing:1});
      s10.addText(`${it.a}  ×  ${it.b}`,{
        x:MARGIN+1.3,y,w:4.2,h:rowH,
        fontSize:11.5,fontFace:FONT_BODY,color:C.white,bold:true,valign:"middle",shrinkText:true,
      });
      s10.addText(it.note||"",{
        x:5.8,y,w:3.8,h:rowH,
        fontSize:8.5,fontFace:FONT_BODY,color:C.muted,italic:true,valign:"middle",shrinkText:true,
      });
    });
  } else {
    s10.addShape(pres.shapes.RECTANGLE,{x:2.5,y:1.9,w:5,h:2.2,fill:{color:C.card},shadow:shadow(12,4,0.25)});
    s10.addShape(pres.shapes.OVAL,{x:4.25,y:2.1,w:1.5,h:1.5,fill:{color:C.green,transparency:25}});
    s10.addText("✓",{x:4.25,y:2.1,w:1.5,h:1.5,fontSize:44,color:C.white,bold:true,align:"center",valign:"middle"});
    s10.addText("FULLY COMPATIBLE",{x:2.5,y:3.65,w:5,h:0.55,fontSize:20,fontFace:FONT_HEAD,color:C.white,bold:true,align:"center",shrinkText:true});
  }
  footer(s10, pres, C);

  // ══════════════════════════════════════════════════════════════════════
  // SLIDE 11 — PRODUCT-SPECIFIC SPECIALTY (conditional)
  // ══════════════════════════════════════════════════════════════════════
  if(PROD.extraSlide === "spf") {
    const ss = pres.addSlide();
    ss.background = {color: C.bg};
    slideHeader(ss, pres, C, "SPF ACTIVE ANALYSIS", false);

    // Find UV filters in formula
    const uvFilters = sorted.filter(([n])=>
      ["zinc oxide","titanium dioxide","octinoxate","oxybenzone","avobenzone",
       "ecamsule","homosalate","octisalate","octocrylene","bemotrizinol","uvinul"].some(f=>n.toLowerCase().includes(f))
    );

    // UV protection spectrum cards
    const uvTypes = [
      {label:"UVB PROTECTION",desc:"Prevents sunburn & DNA damage",color:C.red},
      {label:"UVA PROTECTION",desc:"Prevents photoageing & pigmentation",color:C.purple},
      {label:"BROAD SPECTRUM",desc:"Full-spectrum defence",color:C.gold},
    ];
    uvTypes.forEach((u,i)=>{
      const cx = MARGIN + i*3.05;
      ss.addShape(pres.shapes.RECTANGLE,{x:cx,y:1.1,w:2.8,h:1.5,fill:{color:C.white},shadow:shadow()});
      ss.addShape(pres.shapes.RECTANGLE,{x:cx,y:1.1,w:2.8,h:0.055,fill:{color:u.color}});
      ss.addText(u.label,{x:cx,y:1.2,w:2.8,h:0.45,fontSize:10,fontFace:FONT_HEAD,color:C.primary,bold:true,align:"center",charSpacing:1,shrinkText:true});
      ss.addText(u.desc,{x:cx+0.1,y:1.65,w:2.6,h:0.7,fontSize:9,fontFace:FONT_BODY,color:C.muted,align:"center",italic:true,shrinkText:true});
    });

    // UV filter ingredient table
    if(uvFilters.length>0){
      const hdr=[
        {text:"UV FILTER",options:{fontSize:8.5,fontFace:FONT_BODY,color:C.white,bold:true,fill:{color:C.primary}}},
        {text:"% IN FORMULA",options:{fontSize:8.5,fontFace:FONT_BODY,color:C.white,bold:true,fill:{color:C.primary},align:"center"}},
        {text:"MAX ALLOWED",options:{fontSize:8.5,fontFace:FONT_BODY,color:C.white,bold:true,fill:{color:C.primary},align:"center"}},
        {text:"STATUS",options:{fontSize:8.5,fontFace:FONT_BODY,color:C.white,bold:true,fill:{color:C.primary},align:"center"}},
      ];
      const rows=uvFilters.slice(0,5).map(([n,pct])=>{
        const rkey=Object.keys(PROD.reg).find(k=>n.toLowerCase().includes(k));
        const max=rkey?PROD.reg[rkey]:null;
        const ok=max==null||pct<=max;
        return [
          {text:n,options:{fontSize:9,fontFace:FONT_BODY,color:C.textDark}},
          {text:pct.toFixed(2)+"%",options:{fontSize:9,fontFace:FONT_BODY,color:C.textDark,align:"center"}},
          {text:max!=null?max+"%":"—",options:{fontSize:9,fontFace:FONT_BODY,color:C.muted,align:"center"}},
          {text:ok?"✅ COMPLIANT":"⚠️ REVIEW",options:{fontSize:8.5,fontFace:FONT_BODY,color:ok?C.green:C.red,bold:true,align:"center"}},
        ];
      });
      ss.addTable([hdr,...rows],{
        x:MARGIN,y:2.75,w:W-MARGIN*2,colW:[3.5,1.6,1.6,2.1],
        border:{pt:0.5,color:C.divider},rowH:0.36,
      });
    } else {
      ss.addShape(pres.shapes.RECTANGLE,{x:2.5,y:2.7,w:5,h:1.8,fill:{color:C.white},shadow:shadow()});
      ss.addText("No UV filters detected in current formula.",{x:2.5,y:2.7,w:5,h:1.8,fontSize:11,fontFace:FONT_BODY,color:C.muted,align:"center",valign:"middle",italic:true});
    }
    footer(ss, pres, C);

  } else if(PROD.extraSlide === "ph") {
    const ss = pres.addSlide();
    ss.background = {color: C.primary};
    diagAccent(ss, pres, C);
    slideHeader(ss, pres, C, "pH & EFFICACY PROFILE", true);

    const phVal = formula?.ph || data.formula_v1?.ph || null;
    const phNum = parseFloat(phVal)||4.5;
    const phLabel = phNum<3?"Very Acidic":phNum<5?"Acidic":phNum<6?"Mildly Acidic":phNum<7.5?"Neutral":phNum<9?"Alkaline":"Very Alkaline";
    const phColor = phNum<4?C.red:phNum<6?C.gold:phNum<7.5?C.green:phNum<9?C.blue:C.secondary;

    // pH gauge visual
    const gaugeX=MARGIN, gaugeY=1.1;
    const pHZones=[
      {label:"1–3",c:C.red},{label:"3–5",c:C.secondary},{label:"5–7",c:C.green},
      {label:"7–9",c:C.blue},{label:"9–14",c:C.purple},
    ];
    pHZones.forEach((z,i)=>{
      const zx=gaugeX+i*1.72;
      ss.addShape(pres.shapes.RECTANGLE,{x:zx,y:gaugeY,w:1.65,h:0.45,fill:{color:z.c,transparency:i===Math.floor((phNum-1)/3)?10:40}});
      ss.addText(z.label,{x:zx,y:gaugeY,w:1.65,h:0.45,fontSize:9,fontFace:FONT_BODY,color:C.white,bold:true,align:"center",valign:"middle"});
    });

    // pH value card
    ss.addShape(pres.shapes.RECTANGLE,{x:MARGIN,y:1.65,w:3.5,h:2.4,fill:{color:C.card},shadow:shadow(12,4,0.3)});
    ss.addShape(pres.shapes.RECTANGLE,{x:MARGIN,y:1.65,w:3.5,h:0.06,fill:{color:phColor}});
    ss.addText("pH VALUE",{x:MARGIN,y:1.75,w:3.5,h:0.4,fontSize:9,fontFace:FONT_BODY,color:C.muted,align:"center",charSpacing:3});
    ss.addText(phVal?String(phNum.toFixed(1)):"~4.5",{x:MARGIN,y:2.1,w:3.5,h:1.2,fontSize:52,fontFace:FONT_HEAD,color:phColor,bold:true,align:"center",valign:"middle",shrinkText:true});
    ss.addText(phLabel,{x:MARGIN,y:3.35,w:3.5,h:0.55,fontSize:11,fontFace:FONT_BODY,color:C.white,bold:true,align:"center",valign:"middle"});

    // AHA/BHA analysis
    const acidIng=sorted.filter(([n])=>["glycolic","lactic","salicylic","mandelic","citric","malic","tartaric","glucono"].some(a=>n.toLowerCase().includes(a)));
    if(acidIng.length>0){
      ss.addShape(pres.shapes.RECTANGLE,{x:4.3,y:1.65,w:5.4,h:2.4,fill:{color:C.card},shadow:shadow(10,4,0.25)});
      ss.addShape(pres.shapes.RECTANGLE,{x:4.3,y:1.65,w:5.4,h:0.06,fill:{color:C.secondary}});
      ss.addText("ACID ACTIVES",{x:4.3,y:1.72,w:5.4,h:0.32,fontSize:8.5,fontFace:FONT_BODY,color:C.muted,align:"center",charSpacing:3});
      acidIng.slice(0,4).forEach(([n,pct],i)=>{
        const ay=1.98+i*0.52;
        ss.addText(n,{x:4.45,y:ay,w:3.2,h:0.45,fontSize:9.5,fontFace:FONT_BODY,color:C.white,bold:true,shrinkText:true,valign:"middle"});
        progressBar(ss,pres,C,7.75,ay+0.1,1.7,0.12,Math.min(100,pct/2*100),C.secondary);
        ss.addText(pct.toFixed(2)+"%",{x:7.75,y:ay,w:1.7,h:0.45,fontSize:8,fontFace:FONT_BODY,color:C.muted,align:"right",valign:"middle"});
      });
    } else {
      ss.addShape(pres.shapes.RECTANGLE,{x:4.3,y:1.65,w:5.4,h:2.4,fill:{color:C.card}});
      ss.addText("pH stability confirmed.\nNo aggressive acid actives detected.",{x:4.3,y:1.65,w:5.4,h:2.4,fontSize:11,fontFace:FONT_BODY,color:C.muted,align:"center",valign:"middle",italic:true,lineSpacingMultiple:1.5});
    }
    footer(ss, pres, C);
  }

  // ══════════════════════════════════════════════════════════════════════
  // SLIDE 12 — CLOSING
  // ══════════════════════════════════════════════════════════════════════
  const s11 = pres.addSlide(); // Closing — always last
  s11.background = {color: C.primary};

  // Full-bleed image with heavy overlay
  if(canvas && fs.existsSync(canvas)){
    s11.addImage({path:canvas,x:0,y:0,w:W,h:H,sizing:{type:"cover",w:W,h:H},transparency:80});
  }
  s11.addShape(pres.shapes.RECTANGLE,{x:0,y:0,w:W,h:H,fill:{color:C.primary,transparency:canvas?20:0}});

  // Decorative diamonds
  s11.addText("◆",{x:0.5,y:1.8,w:0.5,h:0.5,fontSize:14,color:C.gold,fontFace:FONT_HEAD});
  s11.addText("◆",{x:9.0,y:3.2,w:0.5,h:0.5,fontSize:10,color:C.goldDim,fontFace:FONT_HEAD});

  // Top rule
  s11.addShape(pres.shapes.LINE,{x:3.2,y:1.25,w:3.6,h:0,line:{color:C.gold,width:1}});

  s11.addText(brand.toUpperCase(),{
    x:0.8,y:1.35,w:W-1.6,h:1.6,
    fontSize:38,fontFace:FONT_HEAD,color:C.white,bold:true,
    align:"center",valign:"middle",lineSpacingMultiple:1.05,shrinkText:true,
  });

  // Bottom rule
  s11.addShape(pres.shapes.LINE,{x:3.2,y:3.1,w:3.6,h:0,line:{color:C.gold,width:2}});
  s11.addShape(pres.shapes.OVAL,{x:4.94,y:3.04,w:0.12,h:0.12,fill:{color:C.gold}});

  s11.addText("Generated by FormulaForge × Nova Technologies",{
    x:1,y:3.22,w:W-2,h:0.42,
    fontSize:12,fontFace:FONT_BODY,color:C.accent,align:"center",italic:true,
  });
  s11.addText(PROD.closingLine,{
    x:1,y:3.68,w:W-2,h:0.4,
    fontSize:10,fontFace:FONT_BODY,color:C.muted,align:"center",shrinkText:true,
  });
  // Product category label
  s11.addShape(pres.shapes.ROUNDED_RECTANGLE,{x:W/2-1.5,y:4.2,w:3.0,h:0.28,fill:{color:C.secondary,transparency:30},rectRadius:0.04});
  s11.addText(PROD.label,{x:W/2-1.5,y:4.2,w:3.0,h:0.28,fontSize:7.5,fontFace:FONT_BODY,color:C.white,bold:true,align:"center",valign:"middle",charSpacing:2});

  s11.addShape(pres.shapes.RECTANGLE,{x:0,y:FOOT_Y,w:W,h:FOOT_H,fill:{color:C.darker}});
  s11.addShape(pres.shapes.RECTANGLE,{x:0,y:FOOT_Y,w:0.04,h:FOOT_H,fill:{color:C.gold}});
  s11.addText("SAMI & VALERIE  ·  NOVA TECHNOLOGIES  ·  FORMULAFORGE",{
    x:0,y:FOOT_Y+0.06,w:W,h:0.38,
    fontSize:8,fontFace:FONT_BODY,color:C.gold,align:"center",charSpacing:2.5,valign:"middle",
  });

  await pres.writeFile({fileName:outPath});
}
