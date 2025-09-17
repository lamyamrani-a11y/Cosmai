Annotation Guidelines — NLP Cosmetics NER

Goal: Extract structured mentions of cosmetics products and tools from tutorial transcripts.

----------------------
Entity Labels:

| Label       | Definition                                        | Examples                                                              |
| ----------- | ------------------------------------------------- | --------------------------------------------------------------------- |
| **BRAND**   | Official brand names                              | `NARS`, `Charlotte Tilbury`, `MAC`, `Too Faced`                       |
| **PRODUCT** | The commercial product name (not including brand) | `Radiant Creamy Concealer`, `Better Than Sex Mascara`, `Tattoo Liner` |
| **SHADE**   | Specific shade, color name, or code               | `Custard`, `NC20`, `#210`, `Trooper Black`                            |
| **TOOL**    | Makeup applicators or accessories                 | `Beauty Blender`, `M433`, `fluffy blending brush`, `powder puff`      |

----------------------
Annotation Unit:
- Work on sentences or small chunks (≈1–3 lines).
- Tag all spans that match one of the entities.
- 
----------------------
Positive Examples:

“I’m applying the NARS Radiant Creamy Concealer in Custard.”
BRAND = NARS
PRODUCT = Radiant Creamy Concealer
SHADE = Custard

“For my liner I use the KVD Beauty Tattoo Liner in Trooper Black.”
BRAND = KVD Beauty
PRODUCT = Tattoo Liner
SHADE = Trooper Black

“Blending with my Morphe M433 brush.”
BRAND = Morphe
TOOL = M433 brush

----------------------
Negative Examples (Don’t Tag):

Functional phrases:
  “I’m going to use …” → do not tag going to.

Generic words without product identity:
  “I need this for coverage.” → this is not a product.

Adjectives or effects:
  “A really full coverage foundation” → full coverage is not a product.

----------------------
Multi-token Spans:

-Always tag the full entity:
  Radiant Creamy Concealer = one PRODUCT span.
  Soft Glam Palette = one PRODUCT span.

-Don’t split unless it’s truly two entities.

----------------------
Brand + Product + Shade:

- Tag each separately:
  “NARS Radiant Creamy Concealer in Custard”
    BRAND = NARS
    PRODUCT = Radiant Creamy Concealer
    SHADE = Custard

----------------------
Tools:

-Branded or generic tools both count.
-Examples:
  Beauty Blender, Real Techniques Sponge, M433 brush, angled brow brush.
-If ambiguous: prefer tagging (we’d rather review later than miss).

----------------------
Labeling Format:

Each sentence saved as JSONL entry with text and entities:

{"text": "I’m applying the NARS Radiant Creamy Concealer in Custard.",
 "entities": [[16, 20, "BRAND"], [21, 45, "PRODUCT"], [49, 56, "SHADE"]]}

Entities = list of [start_char, end_char, label].

----------------------
Ambiguity Rules:

Abbreviations: If clearly a brand (e.g., “CT” → Charlotte Tilbury), tag as BRAND.
Pronouns (“this one”, “that concealer”): don’t tag.
Unrecognized brand/product (not in catalog): still tag — these become prospects.
