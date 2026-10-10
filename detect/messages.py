"""Short trilingual (English / Spanish / Haitian Creole) hazard message per neighborhood.

Grok (xAI API) writes it from the rule engine's facts when XAI_API_KEY is set;
otherwise a fixed template keeps the board working. Cached by state so Grok
is only called when conditions change.
"""
from __future__ import annotations

import hashlib
import json
import logging

from detect import grok

log = logging.getLogger("messages")
_cache: dict[str, dict] = {}

WORDS = {
    "en": {"water": "flooding", "air": "wind/air quality", "land": "evacuation/land", "fire": "heat/fire"},
    "es": {"water": "inundación", "air": "viento/calidad del aire", "land": "evacuación/terreno", "fire": "calor/fuego"},
    "ht": {"water": "inondasyon", "air": "van/kalite lè", "land": "evakyasyon/tè", "fire": "chalè/dife"},
}
TEMPLATES = {
    "ok": {"en": "No significant hazards right now in {name}.",
           "es": "No hay peligros importantes ahora en {name}.",
           "ht": "Pa gen gwo danje kounye a nan {name}."},
    "watch": {"en": "Stay alert in {name}: {forces}. Check official updates.",
              "es": "Manténgase atento en {name}: {forces}. Revise los avisos oficiales.",
              "ht": "Rete vijilan nan {name}: {forces}. Swiv enfòmasyon ofisyèl yo."},
    "alert": {"en": "Hazard in {name}: {forces}. Follow official instructions.",
              "es": "Peligro en {name}: {forces}. Siga las instrucciones oficiales.",
              "ht": "Danje nan {name}: {forces}. Swiv enstriksyon ofisyèl yo."},
}
# One practical tip per force in watch/alert, appended to the template message.
TIPS = {
    "water": {"en": "Avoid flooded roads.", "es": "Evite calles inundadas.", "ht": "Pa pase nan lari ki inonde."},
    "air_quality": {"en": "Air quality: limit outdoor activity, close windows; sensitive groups consider a well-fitting mask.",
                    "es": "Calidad del aire: limite la actividad al aire libre, cierre las ventanas; los grupos sensibles pueden usar una mascarilla ajustada.",
                    "ht": "Kalite lè: diminye aktivite deyò, fèmen fenèt yo; moun ki fragil ka mete yon mask byen ajiste."},
    "storm": {"en": "Follow National Hurricane Center and county updates; secure loose outdoor items.",
              "es": "Siga al Centro Nacional de Huracanes y al condado; asegure los objetos sueltos al aire libre.",
              "ht": "Swiv Sant Nasyonal Siklòn ak konte a; mare oswa rantre bagay ki lage deyò."},
    "fire": {"en": "Drink water, limit time outdoors, use a cooling center; report any new fire or smoke to 911.",
             "es": "Tome agua, limite el tiempo al aire libre, use un centro de enfriamiento; reporte fuego o humo al 911.",
             "ht": "Bwè dlo, pa rete twò lontan deyò, ale nan yon sant refwadisman; rapòte nenpòt dife oswa lafimen bay 911."},
}

PROMPT = """You write very short public-safety notices for residents of {city}.
Neighborhood: {name}
Current status by hazard type (ok/watch/alert/unknown): {statuses}
Facts from public sensors and official alerts:
{facts}

Write ONE plain-language message, at most 2 short sentences (max 35 words): what is going on and one practical
thing to do. Do not invent facts, numbers or places. If everything is ok, say so briefly. Point to official
channels for decisions; never give evacuation orders yourself. Facts starting with SIMULATED are demo data, not
real conditions: do not present them as real.
Return ONLY JSON, no markdown: {{"en": "...", "es": "...", "ht": "..."}} (es = Spanish, ht = Haitian Creole)."""


def _template(name, overall, statuses, tips=None):
    out = {}
    for lang in ("en", "es", "ht"):
        forces = ", ".join(WORDS[lang][f] for f, s in statuses.items() if s in ("watch", "alert"))
        key = overall if overall in TEMPLATES and forces else "ok"
        out[lang] = TEMPLATES[key][lang].format(name=name, forces=forces)
        if key != "ok":
            keys = [(tips or {}).get(f, f) for f, s in statuses.items() if s in ("watch", "alert")]
            out[lang] += "".join(" " + TIPS[k][lang] for k in keys if k in TIPS)
    return out


def neighborhood_message(city_name: str, name: str, overall: str, statuses: dict, facts: list[str],
                         tips: dict | None = None) -> dict:
    """``tips`` maps a force to a tip key when its cause matters (e.g. air -> air_quality or storm)."""
    have_ai = grok.available()
    key = hashlib.sha1(json.dumps([name, statuses, sorted(facts)[:8], have_ai, tips], sort_keys=True).encode()).hexdigest()
    if key in _cache:
        return _cache[key]
    msg = None
    if have_ai:
        try:
            j = grok.parse_json(grok.generate_text(PROMPT.format(
                city=city_name, name=name, statuses=json.dumps(statuses),
                facts="\n".join(f"- {f}" for f in facts[:8]) or "- none"), max_tokens=400))
            if j and all(k in j for k in ("en", "es", "ht")):
                msg = _label_simulated({k: str(j[k])[:300] for k in ("en", "es", "ht")} | {"by": grok.text_model()}, facts)
        except Exception as e:
            log.warning("grok message failed for %s: %s", name, e)
    if msg is None:
        msg = _template(name, overall, statuses, tips) | {"by": "template"}
        if have_ai:
            return msg  # don't cache the fallback; retry Grok next refresh
    _cache[key] = msg
    return msg
