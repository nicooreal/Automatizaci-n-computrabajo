# computrabajo_brave.py — Brave + Selenium (Computrabajo + IA integral)
# Flujo:
# 1) Abrir listado por palabra+ciudad.
# 2) Scrollear hasta ver "Siguiente", recolectar 20 links al DETALLE + href "Siguiente".
# 3) Recorrer 1..20: abrir detalle. Si hay preguntas en modal o embebidas → IA responde (texto, radios, checkboxes, selects, números) y envía de forma robusta. Si no hay preguntas, intenta postular.
# 4) Volver al listado y continuar con el siguiente. Al completar 20, ir a "Siguiente" y repetir.
# 5) Sin pausas de consola. Envío robusto con reintentos, soporte a span.label_box y botón input#btnKiller.

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
import os, time, random, re, unicodedata, json, requests
from difflib import SequenceMatcher
from urllib.parse import urljoin

# ==================== IA: configuración ====================
USE_LLM_FOR_ALL_QUESTIONS = True         # IA SIEMPRE para preguntas de texto
USE_LLM_FALLBACK = True                  # fallback si falla lo anterior
LLM_BACKEND = "ollama"                   # "ollama" | "openai"
LLM_MODEL = "llama3.1"                   # ollama: "llama3.1" / openai: "gpt-4o-mini" u otro
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")

# ==================== CONFIG ====================
BRAVE_PATH = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"

SCRIPT_DIR = os.path.dirname(__file__)
PROFILE_DIR = os.path.join(SCRIPT_DIR, "brave_profile_computrabajo")
os.makedirs(PROFILE_DIR, exist_ok=True)

PALABRAS = ["Soporte Técnico", "Programador", "Administrativo", "IT", "sql", ".net", "Desarrollador", "Help Desk", "Técnico", "Tester", "QA"]
CIUDADES = ["buenos-aires", "capital-federal"]

PAGINAS_MAX = 5
MAX_POR_PALABRA = 10
MAX_TOTAL = 50
KEEP_OPEN_AFTER_RUN = False  # sin pausa final

BASE = "https://ar.computrabajo.com"
CV_JSON_PATH = os.path.join(SCRIPT_DIR, "cv.json")

LOG_VERBOSE = True

# ==================== UTILS / LOG ====================
def log(msg):
    if LOG_VERBOSE:
        print(msg)

def human_sleep(a=0.9, b=1.8):
    time.sleep(random.uniform(a, b))

def slugify_es(texto: str) -> str:
    t = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[^a-zA-Z0-9\s-]", " ", t.lower())
    t = re.sub(r"\s+", "-", t).strip("-")
    t = re.sub(r"-{2,}", "-", t)
    return t

def build_list_url(keyword: str, city_slug: str) -> str:
    kw_slug = slugify_es(keyword)
    return f"{BASE}/trabajo-de-{kw_slug}-en-{city_slug}"

def load_cv_json(path=CV_JSON_PATH):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        log(f"🧾 CV cargado OK desde {path}")
        return data
    except Exception as e:
        print(f"⚠️ No pude cargar {path}: {e}")
        return {}

# ==================== BROWSER ====================
def make_chrome_options():
    opts = webdriver.ChromeOptions()
    opts.binary_location = BRAVE_PATH
    opts.add_argument("--start-maximized")
    opts.add_argument(fr"--user-data-dir={PROFILE_DIR}")
    opts.add_argument("--profile-directory=Default")
    # estabilidad
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--test-type")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    return opts

def start_browser():
    options = make_chrome_options()
    drv = webdriver.Chrome(options=options)
    wait = WebDriverWait(drv, 12)
    return drv, wait

driver, wait = start_browser()
CV = load_cv_json()

# ==================== IA helpers (texto / opciones / números) ====================
def _llm_answer_per_question(question_label: str, cv: dict) -> str | None:
    try:
        q = (question_label or "").strip()
        contacto = cv.get("contacto", {})
        pref     = cv.get("preferencias", {})
        otros    = cv.get("otros", {})
        skills   = cv.get("habilidades", [])[:6]

        prompt = (
            "Eres un asistente de selección y respondes en español con UNA sola frase breve (máx 180 caracteres), "
            "clara, positiva y profesional, directa a la pregunta del reclutador. No inventes datos ni repitas frases genéricas.\n\n"
            f"Pregunta: {q}\n"
            f"Datos del perfil: zona={contacto.get('ubicacion','')}, dispo={pref.get('fecha_inicio','')}, "
            f"movilidad={pref.get('movilidad','')}, viajar={pref.get('viajar','')}, "
            f"inglés={otros.get('idiomas',{}).get('inglés','')}, estudios={otros.get('secundario','')}, "
            f"skills={', '.join(skills)}.\n"
            "Responde solo la frase, sin comillas."
        )

        if LLM_BACKEND == "ollama":
            resp = requests.post(f"{OLLAMA_URL}/api/generate",
                                 json={"model": LLM_MODEL, "prompt": prompt, "stream": False},
                                 timeout=20)
            resp.raise_for_status()
            text = (resp.json() or {}).get("response", "").strip()
        elif LLM_BACKEND == "openai":
            if not OPENAI_API_KEY:
                return None
            headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
            body = {"model": LLM_MODEL,
                    "messages": [{"role": "system", "content": "Responde en español, muy breve, profesional y directo."},
                                 {"role": "user", "content": prompt}],
                    "temperature": 0.6, "max_tokens": 80}
            resp = requests.post(f"{OPENAI_BASE_URL}/chat/completions", json=body, headers=headers, timeout=20)
            resp.raise_for_status()
            text = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        else:
            return None

        text = text.strip(" \n\"'").replace("\n", " ")
        return text[:177] + "…" if len(text) > 180 else (text or None)
    except Exception:
        return None

def _llm_answer_for_fallback(question_label: str, cv: dict):
    try:
        q = (question_label or "").strip()
        contacto = cv.get("contacto", {})
        pref     = cv.get("preferencias", {})
        otros    = cv.get("otros", {})
        skills   = cv.get("habilidades", [])[:6]

        prompt = (
            "Eres un asistente que responde en español con UNA sola frase breve (máx 180 caracteres), "
            "positiva y profesional, directa a la pregunta. No repitas ni inventes.\n\n"
            f"Pregunta: {q}\n"
            f"Datos CV: zona={contacto.get('ubicacion','')}, dispo={pref.get('fecha_inicio','')}, "
            f"movilidad={pref.get('movilidad','')}, viajar={pref.get('viajar','')}, "
            f"inglés={otros.get('idiomas',{}).get('inglés','')}, estudios={otros.get('secundario','')}, "
            f"skills={', '.join(skills)}.\n"
            "Solo la frase."
        )

        if LLM_BACKEND == "ollama":
            resp = requests.post(f"{OLLAMA_URL}/api/generate",
                                 json={"model": LLM_MODEL, "prompt": prompt, "stream": False},
                                 timeout=20)
            resp.raise_for_status()
            text = (resp.json() or {}).get("response", "").strip()
        elif LLM_BACKEND == "openai":
            if not OPENAI_API_KEY:
                return None
            headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
            body = {"model": LLM_MODEL,
                    "messages": [{"role": "system", "content": "Responde en español, breve y profesional."},
                                 {"role": "user", "content": prompt}],
                    "temperature": 0.6, "max_tokens": 80}
            resp = requests.post(f"{OPENAI_BASE_URL}/chat/completions", json=body, headers=headers, timeout=20)
            resp.raise_for_status()
            text = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        else:
            return None

        text = text.strip(" \n\"'").replace("\n", " ")
        return text[:177] + "…" if len(text) > 180 else (text or None)
    except Exception:
        return None

def _norm(s: str) -> str:
    return (s or "").strip().lower()

def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()

def _best_match_idx(prediction: str, options: list[str]) -> int:
    if not prediction or not options: return -1
    scores = [(i, _similar(prediction, opt)) for i, opt in enumerate(options)]
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[0][0] if scores and scores[0][1] >= 0.5 else -1

def _extract_positive_idx(options: list[str]) -> int:
    POS = ["si", "sí", "accept", "acepto", "dispon", "inmed", "full", "sr", "ssr", "biling", "avanz", "complet", "de acuerdo"]
    for i, opt in enumerate(options):
        if any(p in _norm(opt) for p in POS): return i
    return 0 if options else -1

def _llm_choice_for_options(question_label: str, options_texts: list[str], cv: dict) -> str | None:
    try:
        if not options_texts: return None
        q = (question_label or "").strip()
        contacto = cv.get("contacto", {}); pref = cv.get("preferencias", {}); otros = cv.get("otros", {})
        skills = ", ".join(cv.get("habilidades", [])[:6])
        prompt = (
            "Elige UNA opción exacta de la lista que mejor responda la pregunta. "
            "Responde SOLO el TEXTO EXACTO de la opción (sin comillas).\n\n"
            f"Pregunta: {q}\nOpciones: {options_texts}\n"
            f"Perfil: zona={contacto.get('ubicacion','')}, dispo={pref.get('fecha_inicio','')}, movilidad={pref.get('movilidad','')}, "
            f"viajar={pref.get('viajar','')}, inglés={otros.get('idiomas',{}).get('inglés','')}, estudios={otros.get('secundario','')}, skills={skills}."
        )
        if LLM_BACKEND == "ollama":
            resp = requests.post(f"{OLLAMA_URL}/api/generate",
                                 json={"model": LLM_MODEL, "prompt": prompt, "stream": False},
                                 timeout=20)
            resp.raise_for_status(); text = (resp.json() or {}).get("response", "").strip()
        elif LLM_BACKEND == "openai":
            if not OPENAI_API_KEY: return None
            headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
            body = {"model": LLM_MODEL,
                    "messages": [{"role": "system", "content": "Elige UNA opción exacta; responde solo el texto de la opción."},
                                 {"role": "user", "content": prompt}],
                    "temperature": 0.0, "max_tokens": 20}
            resp = requests.post(f"{OPENAI_BASE_URL}/chat/completions", json=body, headers=headers, timeout=20)
            resp.raise_for_status(); text = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        else:
            return None
        return text.strip(" \n\"'") or None
    except Exception:
        return None

def _llm_multi_choice_for_checkboxes(question_label: str, options_texts: list[str], cv: dict) -> list[str] | None:
    try:
        if not options_texts: return None
        q = (question_label or "").strip()
        contacto = cv.get("contacto", {}); pref = cv.get("preferencias", {}); otros = cv.get("otros", {})
        skills = ", ".join(cv.get("habilidades", [])[:6])
        prompt = (
            "Elige TODAS las opciones relevantes (0..N). "
            "Responde SOLO con los textos exactos separados por comas. Si ninguna aplica, responde NINGUNA.\n\n"
            f"Pregunta: {q}\nOpciones: {options_texts}\n"
            f"Perfil: zona={contacto.get('ubicacion','')}, dispo={pref.get('fecha_inicio','')}, movilidad={pref.get('movilidad','')}, "
            f"viajar={pref.get('viajar','')}, inglés={otros.get('idiomas',{}).get('inglés','')}, estudios={otros.get('secundario','')}, skills={skills}."
        )
        if LLM_BACKEND == "ollama":
            resp = requests.post(f"{OLLAMA_URL}/api/generate",
                                 json={"model": LLM_MODEL, "prompt": prompt, "stream": False},
                                 timeout=20)
            resp.raise_for_status(); text = (resp.json() or {}).get("response", "").strip()
        elif LLM_BACKEND == "openai":
            if not OPENAI_API_KEY: return None
            headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
            body = {"model": LLM_MODEL,
                    "messages": [{"role": "system", "content": "Responde solo textos exactos separados por comas, o NINGUNA."},
                                 {"role": "user", "content": prompt}],
                    "temperature": 0.0, "max_tokens": 60}
            resp = requests.post(f"{OPENAI_BASE_URL}/chat/completions", json=body, headers=headers, timeout=20)
            resp.raise_for_status(); text = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        else:
            return None

        if _norm(text) == "ninguna": return []
        parts = [p.strip(" \n\"'") for p in text.split(",") if p.strip()]
        return parts or None
    except Exception:
        return None

def _llm_number_for_question(question_label: str, cv: dict, default: int = 2, min_v: int = 0, max_v: int = 50) -> int:
    try:
        q = (question_label or "").strip()
        contacto = cv.get("contacto", {}); pref = cv.get("preferencias", {}); otros = cv.get("otros", {})
        skills = ", ".join(cv.get("habilidades", [])[:6])
        prompt = (
            "Devuelve SOLO un número entero que responda a la pregunta. Si son años de experiencia, sé coherente con el perfil.\n\n"
            f"Pregunta: {q}\n"
            f"Datos: dispo={pref.get('fecha_inicio','')}, movilidad={pref.get('movilidad','')}, viajar={pref.get('viajar','')}, "
            f"inglés={otros.get('idiomas',{}).get('inglés','')}, estudios={otros.get('secundario','')}, skills={skills}."
        )
        if LLM_BACKEND == "ollama":
            resp = requests.post(f"{OLLAMA_URL}/api/generate",
                                 json={"model": LLM_MODEL, "prompt": prompt, "stream": False},
                                 timeout=20)
            resp.raise_for_status(); text = (resp.json() or {}).get("response", "").strip()
        elif LLM_BACKEND == "openai":
            if not OPENAI_API_KEY: return default
            headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
            body = {"model": LLM_MODEL,
                    "messages": [{"role": "system", "content": "Responde solo con un número entero."},
                                 {"role": "user", "content": prompt}],
                    "temperature": 0.0, "max_tokens": 10}
            resp = requests.post(f"{OPENAI_BASE_URL}/chat/completions", json=body, headers=headers, timeout=20)
            resp.raise_for_status(); text = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        else:
            return default

        digits = re.findall(r"-?\d+", text)
        val = int(digits[0]) if digits else default
        return max(min_v, min(max_v, val))
    except Exception:
        return default

# ==================== Helpers DOM extra ====================
def _closest_label_text(el) -> str:
    """Busca el texto de label asociado o el texto más cercano arriba."""
    try:
        el_id = el.get_attribute("id") or ""
        if el_id:
            try:
                lab = driver.find_element(By.CSS_SELECTOR, f"label[for='{el_id}']")
                t = (lab.text or "").strip()
                if t: return t
            except: pass
        try:
            lab = el.find_element(By.XPATH, "ancestor::label[1]")
            t = (lab.text or "").strip()
            if t: return t
        except: pass
        for xp in [
            "ancestor::div[contains(@class,'field_')][1]//label[1]",
            "ancestor::div[contains(@class,'group')][1]//label[1]",
            "ancestor::fieldset[1]//legend[1]",
            "preceding::label[1]"
        ]:
            try:
                lab = el.find_element(By.XPATH, xp)
                t = (lab.text or "").strip()
                if t: return t
            except: pass
    except:
        pass
    return ""

def _click_input_or_label(input_el) -> bool:
    """Click en input; si está oculto, usar label[for] o span.label_box asociado."""
    try:
        if input_el.is_displayed():
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", input_el)
            driver.execute_script("arguments[0].click();", input_el)
            return True
    except: pass
    try:
        el_id = input_el.get_attribute("id") or ""
        if el_id:
            lab = driver.find_element(By.CSS_SELECTOR, f"label[for='{el_id}']")
            if lab.is_displayed():
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", lab)
                driver.execute_script("arguments[0].click();", lab)
                return True
    except: pass
    try:
        span = input_el.find_element(By.XPATH, "ancestor::label[1]//span[contains(@class,'label_box')]")
        if span.is_displayed():
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", span)
            driver.execute_script("arguments[0].click();", span)
            return True
    except: pass
    try:
        span = input_el.find_element(By.XPATH, "following-sibling::span[contains(@class,'label_box')][1]")
        if span.is_displayed():
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", span)
            driver.execute_script("arguments[0].click();", span)
            return True
    except: pass
    return False

# ==================== Modal detection & dumps ====================
def is_selection_modal_open(timeout=2):
    candidates = [
        "div.box_detail", "div.popup", "div.popup-complaint",
        "div.popup-skill-offer", "div.bg_brand_light",
        "form[action*='apply']",
        "div[data-offers-grid-detail-container]"
    ]
    end = time.time() + timeout
    while time.time() < end:
        for sel in candidates:
            try:
                el = driver.find_element(By.CSS_SELECTOR, sel)
                if el.is_displayed():
                    return True
            except:
                pass
        time.sleep(0.2)
    return False

def debug_dump_modal():
    path = os.path.join(SCRIPT_DIR, "ct_modal_dump.html")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"🧪 Dump HTML guardado: {path}")
    except Exception as e:
        print(f"⚠️ No pude guardar dump: {e}")

# ==================== IA en opciones / inputs con soporte a span.label_box ====================
def _pick_positive_radio(radios, question_label: str = ""):
    opts = []
    for r in radios:
        try:
            txt = ""
            val = (r.get_attribute("value") or "").strip()
            rid = r.get_attribute("id") or ""
            if rid:
                try:
                    lab = driver.find_element(By.CSS_SELECTOR, f"label[for='{rid}']")
                    txt = (lab.text or "").strip()
                except: pass
            if not txt:
                try:
                    txt = r.find_element(By.XPATH, "ancestor::label[1]//span[contains(@class,'label_box')]").text.strip()
                except: pass
            if not txt: txt = val or "Opción"
            opts.append(txt)
        except:
            opts.append("Opción")

    idx = -1
    if opts:
        pred = _llm_choice_for_options(question_label, opts, CV)
        if pred: idx = _best_match_idx(pred, opts)
    if idx < 0 and opts: idx = _extract_positive_idx(opts)

    if 0 <= idx < len(radios):
        return _click_input_or_label(radios[idx])

    for r in radios:
        if _click_input_or_label(r): return True
    return False

def _check_all_checkboxes(container, question_label: str = ""):
    cbs = container.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
    if not cbs: return False
    opts = []
    for cb in cbs:
        try:
            txt = ""
            cid = cb.get_attribute("id") or ""
            if cid:
                try:
                    lab = driver.find_element(By.CSS_SELECTOR, f"label[for='{cid}']")
                    txt = (lab.text or "").strip()
                except: pass
            if not txt:
                try:
                    txt = cb.find_element(By.XPATH, "ancestor::label[1]//span[contains(@class,'label_box')]").text.strip()
                except: pass
            if not txt: txt = (cb.get_attribute("value") or "").strip() or "Opción"
            opts.append(txt)
        except:
            opts.append("Opción")

    decided = _llm_multi_choice_for_checkboxes(question_label, opts, CV)
    ok = False
    if decided is not None:
        targets = {_norm(d) for d in decided}
        for cb, txt in zip(cbs, opts):
            try:
                if _norm(txt) in targets and not cb.is_selected():
                    if _click_input_or_label(cb): ok = True
            except: pass
        return ok

    for cb in cbs:
        try:
            if not cb.is_selected():
                if _click_input_or_label(cb): ok = True
        except: pass
    return ok

def _select_positive_option(select_el, question_label: str = ""):
    try:
        sel = Select(select_el)
        options = sel.options
        texts = [(opt.text or "").strip() or (opt.get_attribute("value") or "").strip() or "Opción" for opt in options]
        pred = _llm_choice_for_options(question_label, texts, CV)
        if pred:
            idx = _best_match_idx(pred, texts)
            if 0 <= idx < len(options):
                sel.select_by_visible_text(options[idx].text)
                return True
        idx = _extract_positive_idx(texts)
        if 0 <= idx < len(options):
            sel.select_by_visible_text(options[idx].text)
            return True
        for opt in options:
            if (opt.text or "").strip():
                sel.select_by_visible_text(opt.text)
                return True
    except: pass
    return False

def _fill_numeric_inputs(block, question_label: str):
    ok = False
    for inp in block.find_elements(By.CSS_SELECTOR, "input[type='number']"):
        try:
            if not inp.is_displayed(): continue
            val = _llm_number_for_question(question_label, CV, default=2, min_v=0, max_v=50)
            inp.clear(); inp.send_keys(str(val)); ok = True
        except:
            pass
    return ok

# ==================== Click robusto de envío ====================
def _close_common_overlays():
    candidates_xpath = [
        "//button[contains(., 'Aceptar') or contains(., 'Entendido') or contains(., 'Cerrar')]",
        "//div[contains(@class,'close') or contains(@class,'modal')]/button",
        "//span[contains(., 'Cerrar')]/ancestor::button",
    ]
    for xp in candidates_xpath:
        try:
            for el in driver.find_elements(By.XPATH, xp):
                if el.is_displayed():
                    driver.execute_script("arguments[0].click();", el)
                    time.sleep(0.2)
        except:
            pass

def _find_submit_buttons():
    xpaths = [
        # específicos CT candidato
        "//input[@id='btnKiller' and @type='submit']",
        "//input[@type='submit' and contains(@value,'Enviar mi CV')]",
        # genéricos
        "//*[self::button or self::a or @role='button'][contains(normalize-space(.), 'Postularme')]",
        "//*[self::button or self::a or @role='button'][contains(normalize-space(.), 'Postular')]",
        "//*[self::button or self::a or @role='button'][contains(normalize-space(.), 'Aplicar')]",
        "//*[self::button or self::a or @role='button'][contains(normalize-space(.), 'Enviar mi CV')]",
        "//*[self::button or self::a or @role='button'][contains(normalize-space(.), 'Enviar')]",
        "//*[self::button or self::a or @role='button'][contains(normalize-space(.), 'Continuar')]",
        "//a[contains(translate(@href,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'postular')]",
        "//a[contains(translate(@href,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'aplicar')]",
        "//button[@type='submit']",
        "//input[@type='submit']",
    ]
    found = []
    for xp in xpaths:
        try:
            found += driver.find_elements(By.XPATH, xp)
        except: pass
    visibles = []
    for el in found:
        try:
            if el.is_displayed():
                size = el.size or {}
                if size.get("width", 0) > 2 and size.get("height", 0) > 2:
                    visibles.append(el)
        except: pass
    return visibles

def _robust_click(el) -> bool:
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.2)
        try:
            ActionChains(driver).move_to_element(el).pause(0.05).click(el).perform(); return True
        except:
            pass
        try:
            driver.execute_script("arguments[0].click();", el); return True
        except:
            pass
        try:
            el.send_keys(Keys.ENTER); return True
        except:
            pass
    except:
        pass
    return False

def _submit_nearest_form(el) -> bool:
    try:
        form = el.find_element(By.XPATH, "ancestor::form[1]")
        if form:
            driver.execute_script("arguments[0].submit();", form); return True
    except:
        pass
    return False

def _button_submit_with_retries(max_attempts=4) -> bool:
    last_err = None
    for _ in range(1, max_attempts+1):
        btns = _find_submit_buttons()
        if not btns:
            _close_common_overlays(); time.sleep(0.2)
            btns = _find_submit_buttons()

        if not btns:
            try: ActionChains(driver).send_keys(Keys.ENTER).perform()
            except: pass
            try:
                for f in driver.find_elements(By.TAG_NAME, "form"):
                    if f.is_displayed():
                        driver.execute_script("arguments[0].submit();", f); return True
            except Exception as e:
                last_err = e
            continue

        for b in btns:
            if _robust_click(b):
                time.sleep(0.6); return True
            if _submit_nearest_form(b):
                time.sleep(0.6); return True

        _close_common_overlays(); time.sleep(0.3)

    if last_err: log(f"⚠️ Error al enviar: {last_err}")
    return False

def _wait_modal_close_or_feedback(timeout=8) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if not is_selection_modal_open(timeout=0.4):
            return True
        time.sleep(0.2)
    return False

# ==================== Texto: composición con IA siempre primero ====================
def _compose_text_answer(question_label: str, cv: dict) -> str:
    if USE_LLM_FOR_ALL_QUESTIONS:
        ai = _llm_answer_per_question(question_label, cv)
        if ai: return ai

    q = (question_label or "").lower()
    pref   = cv.get("preferencias", {})
    otros  = cv.get("otros", {})
    skills = cv.get("habilidades", [])
    cont   = cv.get("contacto", {})

    def pick(*opts):
        import random
        return random.choice([o for o in opts if o])

    zona      = cont.get("ubicacion", "CABA / GBA")
    tel       = cont.get("telefono") or cont.get("celular")
    ingles    = otros.get("idiomas", {}).get("inglés", "") or "Intermedio"
    disp      = pref.get("fecha_inicio", "Inmediata")
    movilidad = pref.get("movilidad", "Sí")
    viajar    = pref.get("viajar", "Sí")
    sueldo    = pref.get("sueldo_neto_mensual") or pref.get("sueldo_bruto_mensual") or "A convenir"
    secu      = otros.get("secundario", "Completo")
    top_sk    = ", ".join(skills[:3]) if skills else ""

    if any(k in q for k in ["ingl", "english"]): return pick(f"Nivel {ingles}.", f"Inglés {ingles}.", f"Manejo de inglés: {ingles}.")
    if any(k in q for k in ["salario","sueldo","remuner"]): return pick(f"{sueldo}.", f"Mi expectativa es {sueldo}.", f"Expectativa salarial: {sueldo}.")
    if "experien" in q and top_sk: return pick(f"Experiencia en {top_sk}.", f"Tengo experiencia en {top_sk}.")
    if any(k in q for k in ["disponibilidad","inicio","cuando podés","cuando podes"]): return pick(f"{disp}.", f"Disponibilidad {disp}.", f"Puedo iniciar {disp}.")
    if "viajar" in q: return pick(viajar, f"{viajar}.", f"Disponibilidad para viajar: {viajar}.")
    if any(k in q for k in ["movilidad","veh"]): return pick(movilidad, f"{movilidad}.", f"Cuento con movilidad: {movilidad}.")
    if any(k in q for k in ["estudios","secund"]): return pick(f"Secundario {secu}.", f"Estudios: secundario {secu}.")
    if any(k in q for k in ["zona","resid","domicilio","dónde viv","donde viv"]): return pick(zona, f"{zona}.", f"Resido en {zona}.")
    if any(k in q for k in ["tel","cel","contacto"]): return tel or "Disponible por este medio."

    if USE_LLM_FALLBACK:
        ai2 = _llm_answer_for_fallback(question_label, cv)
        if ai2: return ai2

    base = ["Sí, cuento con la experiencia requerida.",
            "Sí, estoy disponible.",
            "Sí, puedo adaptarme a los requerimientos del puesto.",
            "Sí, no tengo inconvenientes."]
    return pick(*base)

# ==================== Completar preguntas (modal o embebidas) y enviar ====================
def fill_questions_anywhere_and_submit(cv: dict) -> bool:
    ok_algo = False

    # 1) Detectar modo
    modal_mode = is_selection_modal_open(timeout=0.8)
    if modal_mode:
        containers = []
        for sel in ["div.box_detail", "div.popup", "div.popup-skill-offer", "form[action*='apply']"]:
            containers += driver.find_elements(By.CSS_SELECTOR, sel)
        containers = [c for c in containers if c.is_displayed()]
    else:
        containers = []
        for sel in [
            "form[action*='apply']", "article form", "article",
            "div.field_textarea", "div.field_radio_box", "section",
            "div[data-offers-grid-detail-container]"
        ]:
            containers += driver.find_elements(By.CSS_SELECTOR, sel)
        containers = [c for c in containers if c.is_displayed()]

    # 2) Por contenedor: radios, checks, selects, inputs numéricos, textareas e inputs
    for cont in containers:
        try:
            label_ctx = ""
            try:
                label_ctx = cont.find_element(By.CSS_SELECTOR, "label").text.strip()
            except:
                label_ctx = (cont.text or "").strip()
        except:
            label_ctx = ""

        radios = cont.find_elements(By.CSS_SELECTOR, "input[type='radio']")
        if radios and _pick_positive_radio(radios, question_label=label_ctx): ok_algo = True

        if _check_all_checkboxes(cont, question_label=label_ctx): ok_algo = True

        for s in cont.find_elements(By.TAG_NAME, "select"):
            if _select_positive_option(s, question_label=label_ctx): ok_algo = True

        if _fill_numeric_inputs(cont, label_ctx): ok_algo = True

        for ta in cont.find_elements(By.TAG_NAME, "textarea"):
            try:
                if ta.is_displayed() and (ta.get_attribute("value") or "").strip() == "":
                    qtxt = _closest_label_text(ta) or label_ctx
                    ans = _compose_text_answer(qtxt, cv)
                    ta.clear(); ta.send_keys(ans); ok_algo = True
            except: pass

        for inp in cont.find_elements(By.CSS_SELECTOR, "input[type='text'],input[type='email']"):
            try:
                if inp.is_displayed() and (inp.get_attribute("value") or "").strip() == "":
                    qtxt = _closest_label_text(inp) or label_ctx
                    ans = _compose_text_answer(qtxt, cv)
                    inp.clear(); inp.send_keys(ans); ok_algo = True
            except: pass

    # 3) Pasada GLOBAL: por si quedaron textareas sueltos (como sueldo bruto)
    for ta in driver.find_elements(By.TAG_NAME, "textarea"):
        try:
            if ta.is_displayed() and (ta.get_attribute("value") or "").strip() == "":
                qtxt = _closest_label_text(ta)
                ans = _compose_text_answer(qtxt, cv)
                ta.clear(); ta.send_keys(ans); ok_algo = True
        except: pass

    # 4) Enviar (botón robusto)
    sent = _button_submit_with_retries(max_attempts=4)
    if sent:
        _wait_modal_close_or_feedback(timeout=8)
        return True

    return ok_algo

# ==================== Listado: scroll + recolección de 20 + next ====================
def ensure_logged_in():
    driver.get(BASE + "/")
    human_sleep(1.2, 2.0)
    page = driver.page_source
    if ("Acceder" in page) or ("Ingresar" in page):
        log("🔐 No estás logueado (se ve 'Acceder/Ingresar'). Sigo sin pausar; algunas postulaciones pueden fallar.")

def _next_button_elements():
    sels = ["a[rel='next']", "a[aria-label*='Siguiente' i]", "a.pager__next", "a[title*='Siguiente' i]"]
    btns = []
    for s in sels:
        btns += driver.find_elements(By.CSS_SELECTOR, s)
    return [b for b in btns if b.is_displayed() and (b.get_attribute("href") or "").strip()]

def _scroll_until_next_and_collect(max_items: int = 20):
    # Scroll hasta ver “Siguiente” estabilizado
    same_rounds, last_count, safety = 0, -1, 0
    while True:
        safety += 1
        arts = driver.find_elements(By.CSS_SELECTOR, "article[data-offers-grid-offer-item-container], article.box_offer")
        cur_count = len(arts)
        if cur_count == last_count: same_rounds += 1
        else: same_rounds, last_count = 0, cur_count
        next_btns = _next_button_elements()
        if (next_btns and same_rounds >= 2) or safety >= 25: break
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        human_sleep(0.5, 0.9)

    # Recolectar hasta 20 links al DETALLE
    detail_links, seen = [], set()
    arts = driver.find_elements(By.CSS_SELECTOR, "article[data-offers-grid-offer-item-container], article.box_offer")
    for art in arts:
        href = ""
        for sel in ["h2 a.js-o-link.fc_base", "h2 a.fc_base", "h2 a", "a.js-o-link", "a.fc_base", "a[href*='/ofertas-trabajo/']","a[href*='/ofertas-de-trabajo/']"]:
            try:
                a = art.find_element(By.CSS_SELECTOR, sel)
                if a and a.is_displayed():
                    href = a.get_attribute("href") or ""
                    if href:
                        href = urljoin(driver.current_url, href); break
            except:
                continue
        if not href:
            data_id = art.get_attribute("id") or art.get_attribute("data-offer-id") or ""
            if data_id and re.fullmatch(r"[A-Fa-f0-9]{32,}", data_id):
                base_no_hash = driver.current_url.split("#")[0]
                href = f"{base_no_hash}#{data_id}"
        if href and href not in seen:
            seen.add(href); detail_links.append(href)
            if len(detail_links) >= max_items: break

    next_href = None
    btns = _next_button_elements()
    if btns:
        next_href = urljoin(driver.current_url, btns[0].get_attribute("href"))

    return detail_links, next_href

# ==================== Postulación desde detalle/hash ====================
def try_inline_apply_on_hash(hash_url: str) -> bool:
    driver.get(hash_url)
    human_sleep(0.9, 1.5)

    if "#" not in hash_url: return False
    data_id = hash_url.split("#", 1)[1].strip()
    if not data_id: return False

    try:
        art = WebDriverWait(driver, 6).until(EC.presence_of_element_located((By.CSS_SELECTOR, f"article#{data_id}")))
    except:
        return False

    try:
        apply_span = art.find_element(By.CSS_SELECTOR, "[shortcut-apply-ac]")
    except:
        apply_span = None

    if apply_span:
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", apply_span)
            human_sleep(0.3, 0.6)
            driver.execute_script("arguments[0].click();", apply_span)
            human_sleep(0.8, 1.4)

            if fill_questions_anywhere_and_submit(CV):
                print(f"  ✅ Postulación enviada (inline) — {hash_url}")
                return True

            if "/acceso" in (driver.current_url or ""):
                log("🔐 Redirigió a login (inline). Omito esta postulación y continúo.")
                return False
        except:
            pass

    return False

def try_detail_apply_from_url(detail_url: str) -> bool:
    driver.get(detail_url)
    human_sleep(1.0, 1.6)

    # 1) Intentar encontrar y clickear "Postularme"/"Postular"/"Aplicar"/"Enviar"
    clicked = False
    try:
        cand = _find_submit_buttons()
        if not cand:
            human_sleep(0.4, 0.8)
            cand = _find_submit_buttons()

        for el in cand:
            txt = (el.text or "").strip().lower()
            href = (el.get_attribute("href") or "").lower()
            if any(k in txt for k in ["postularme", "postular", "aplicar", "enviar"]) or \
               any(k in href for k in ["postular", "aplicar"]):
                if _robust_click(el):
                    clicked = True
                    human_sleep(0.6, 1.0)
                    break
    except:
        pass

    # 2) Con o sin click previo, completar preguntas (modal o embebidas) y enviar
    ok = fill_questions_anywhere_and_submit(CV)
    if ok:
        return True

    # 3) Si no había preguntas ni envío, considerar que el click ya postuló
    return clicked and not is_selection_modal_open(timeout=0.5)

# ==================== Paginado según el flujo acordado ====================
def procesar_listado(keyword: str, city_slug: str, paginas_max: int, max_kw: int, max_total_ref) -> int:
    url_list = build_list_url(keyword, city_slug)
    driver.get(url_list)
    human_sleep(1.2, 1.8)

    postuladas_kw = 0
    pagina = 1

    while pagina <= paginas_max and postuladas_kw < max_kw and max_total_ref[0] < MAX_TOTAL:
        links, next_href = _scroll_until_next_and_collect(max_items=20)
        print(f"   ↳ Página {pagina}: {len(links)} avisos (esperados ≈20)")
        list_url = driver.current_url

        for idx, link in enumerate(links, 1):
            if postuladas_kw >= max_kw or max_total_ref[0] >= MAX_TOTAL:
                break

            ok = False
            if "#" in link:
                ok = try_inline_apply_on_hash(link)
                if not ok:  # fallback al detalle directo
                    base = link.split("#")[0]
                    ok = try_detail_apply_from_url(base)
            else:
                ok = try_detail_apply_from_url(link)

            if ok:
                postuladas_kw += 1
                max_total_ref[0] += 1
                print(f"     #{idx:02d} OK  — {link}")
            else:
                print(f"     #{idx:02d} FAIL — {link}")

            # volver al listado y asegurar
            try:
                driver.back(); human_sleep(0.8, 1.2)
                if "/ofertas-trabajo/" in (driver.current_url or "") or driver.current_url == link:
                    driver.get(list_url); human_sleep(1.0, 1.6)
            except:
                driver.get(list_url); human_sleep(1.0, 1.6)

        if postuladas_kw >= max_kw or max_total_ref[0] >= MAX_TOTAL:
            break

        if not next_href:
            print("   ↪️ No encontré 'Siguiente'. Fin del listado.")
            break
        driver.get(next_href); human_sleep(1.2, 1.8)
        pagina += 1

    return postuladas_kw

# ==================== MAIN ====================
def main():
    print("🔎 Iniciando…")
    ensure_logged_in()

    total_ref = [0]
    for kw in PALABRAS:
        if total_ref[0] >= MAX_TOTAL: break
        print(f"\n🔹 Buscando: {kw}")
        for city in CIUDADES:
            if total_ref[0] >= MAX_TOTAL: break
            print(f"   • Ciudad: {city}")
            hechas = procesar_listado(
                keyword=kw,
                city_slug=city,
                paginas_max=PAGINAS_MAX,
                max_kw=MAX_POR_PALABRA,
                max_total_ref=total_ref
            )
            print(f"   → Postuladas en '{kw}' / {city}: {hechas}")

    print(f"\n🎉 Listo. Postulaciones realizadas: {total_ref[0]}")
    try: driver.quit()
    except: pass

if __name__ == "__main__":
    main()
