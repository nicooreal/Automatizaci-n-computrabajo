# computrabajo_brave.py — Brave + Selenium (Computrabajo)
# Algoritmo fiel al pedido:
# 1) Para cada keyword y ciudad: abrir URL canónica de listado.
# 2) En CADA página del listado: recolectar TODOS los hash-links (baseURL#<data-id>).
# 3) Iterar esa lista: abrir hash-link, intentar "Postular" desde la tarjeta (shortcut-apply-ac).
#    Si no se puede, abrir el detalle y clickear "Postularme" (span.b_primary.big).
# 4) Al terminar esa lista, LIMPIAR y pasar a la siguiente página del portal.
# 5) Repetir hasta PAGINAS_MAX / límites.

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import os, time, random, re, unicodedata

# ==================== CONFIG ====================
BRAVE_PATH = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"

SCRIPT_DIR = os.path.dirname(__file__)
PROFILE_DIR = os.path.join(SCRIPT_DIR, "brave_profile_computrabajo")
os.makedirs(PROFILE_DIR, exist_ok=True)

PALABRAS = ["Soporte Técnico", "tecnologia","sql",".net","c++","heldesk","administracion","it","it support","it soporte","it helpdesk"]
# ciudades según el dominio de Computrabajo AR
CIUDADES = ["buenos-aires", "capital-federal"]

PAGINAS_MAX = 4           # cuántas páginas del portal por búsqueda
MAX_POR_PALABRA = 8       # límite de postulaciones por (keyword x ciudad)
MAX_TOTAL = 50            # límite global de postulaciones
KEEP_OPEN_AFTER_RUN = True

BASE = "https://ar.computrabajo.com"

# ==================== UTILS ====================
def human_sleep(a=0.9, b=1.8):
    time.sleep(random.uniform(a, b))

def slugify_es(texto: str) -> str:
    t = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[^a-zA-Z0-9\s-]", " ", t.lower())
    t = re.sub(r"\s+", "-", t).strip("-")
    t = re.sub(r"-{2,}", "-", t)
    return t

def build_list_url(keyword: str, city_slug: str) -> str:
    # formato validado: https://ar.computrabajo.com/trabajo-de-<kw>-en-<ciudad>
    kw_slug = slugify_es(keyword)
    return f"{BASE}/trabajo-de-{kw_slug}-en-{city_slug}"

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

# ==================== CORE HELPERS ====================
def ensure_logged_in():
    driver.get(BASE + "/")
    human_sleep(1.2, 2.0)
    page = driver.page_source
    if ("Acceder" in page) or ("Ingresar" in page):
        print("👉 Iniciá sesión en Computrabajo en la ventana de Brave. Cuando termines, presioná Enter acá.")
        try: input()
        except KeyboardInterrupt: pass

def scroll_soft(times=2, pause=0.6):
    for _ in range(times):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(pause)

def collect_hash_links_on_page() -> list:
    """
    Recolecta hash-links del listado:
    baseListURL#<data-id> usando los <article data-offers-grid-offer-item-container id="...">
    """
    base_no_hash = driver.current_url.split("#")[0]
    articles = driver.find_elements(By.CSS_SELECTOR, "article[data-offers-grid-offer-item-container][id]")
    links = []
    for art in articles:
        data_id = art.get_attribute("id") or ""
        if data_id and re.fullmatch(r"[A-F0-9]{32,}", data_id):
            links.append(f"{base_no_hash}#{data_id}")
    # únicos, orden estable
    seen = set(); uniq = []
    for u in links:
        if u not in seen:
            seen.add(u); uniq.append(u)
    return uniq

def goto_next_page() -> bool:
    try:
        next_btn = driver.find_element(By.CSS_SELECTOR, "a[rel='next']")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", next_btn)
        human_sleep(0.4, 0.8)
        next_btn.click()
        human_sleep(1.2, 1.8)
        return True
    except:
        return False

def try_inline_apply_on_hash(hash_url: str) -> bool:
    """
    Abre el hash-link (listado anclado al aviso) y trata de disparar el "Postular" inline
    dentro de la tarjeta: <span shortcut-apply-ac ...> (aunque esté dentro del bubble).
    Si no puede, retorna False para que probemos el detalle.
    """
    driver.get(hash_url)
    human_sleep(0.9, 1.5)

    # obtener ID del hash
    if "#" not in hash_url:
        return False
    data_id = hash_url.split("#", 1)[1].strip()
    if not data_id:
        return False

    # localizar la tarjeta (article) y el botón "shortcut-apply-ac"
    try:
        art = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, f"article#{data_id}"))
        )
    except:
        return False

    # a veces el "bubble" necesita hover, pero podemos invocar click vía JS
    # selector del atajo de postular en la tarjeta
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
            # si redirige a acceso/login, pedir login y continuar
            if "/acceso" in (driver.current_url or ""):
                print("🔐 Redirigió a login de candidato. Iniciá sesión y presioná Enter para seguir…")
                try: input()
                except KeyboardInterrupt: pass
                return False  # volveremos a intentar en detalle
            print(f"  ✅ Postulación enviada (inline) — {hash_url}")
            return True
        except:
            pass

    return False  # que pruebe el flujo de detalle

def try_detail_apply_from_hash(hash_url: str) -> bool:
    """
    Desde el hash-link, abre el enlace al detalle (a.js-o-link.fc_base) dentro del article
    y cliquea el botón del detalle: <span class="b_primary big">Postularme</span>
    """
    driver.get(hash_url)
    human_sleep(0.9, 1.5)

    # id del aviso
    if "#" not in hash_url:
        return False
    data_id = hash_url.split("#", 1)[1].strip()
    if not data_id:
        return False

    # localizar tarjeta y abrir el enlace al detalle
    try:
        art = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, f"article#{data_id}"))
        )
    except:
        return False

    # link principal del aviso
    detail_link = None
    try:
        detail_link = art.find_element(By.CSS_SELECTOR, "h2 a.js-o-link.fc_base")
    except:
        pass

    if detail_link:
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", detail_link)
            human_sleep(0.3, 0.6)
            detail_link.click()
            human_sleep(1.2, 1.8)
        except:
            return False
    else:
        return False

    # en la página de detalle, botón "Postularme"
    try:
        btn = WebDriverWait(driver, 6).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "span.b_primary.big"))
        )
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        human_sleep(0.4, 0.8)
        btn.click()
        human_sleep(0.8, 1.2)
        if "/acceso" in (driver.current_url or ""):
            print("🔐 Redirigió a login de candidato. Iniciá sesión y presioná Enter para seguir…")
            try: input()
            except KeyboardInterrupt: pass
            return False
        print(f"  ✅ Postulación enviada (detalle) — {driver.current_url}")
        return True
    except:
        print(f"  ↪️ Sin botón 'Postularme' en detalle — {driver.current_url}")
        return False

def procesar_listado(keyword: str, city_slug: str, paginas_max: int, max_kw: int, max_total_ref) -> int:
    """
    Recorre el listado por páginas:
    - por cada página: recolecta hash-links, itera y postula, limpia lista, next page.
    - respeta límites por keyword (max_kw) y global (max_total_ref[0]).
    """
    url_list = build_list_url(keyword, city_slug)
    driver.get(url_list)
    human_sleep(1.2, 1.8)

    postuladas_kw = 0
    pagina = 1
    while pagina <= paginas_max and postuladas_kw < max_kw and max_total_ref[0] < MAX_TOTAL:
        scroll_soft(2, 0.5)
        links = collect_hash_links_on_page()
        print(f"   ↳ Página {pagina}: {len(links)} avisos (hashes)")

        for hlink in links:
            if postuladas_kw >= max_kw or max_total_ref[0] >= MAX_TOTAL:
                break

            # 1) intentar inline en la tarjeta del listado
            ok = try_inline_apply_on_hash(hlink)
            if not ok:
                # 2) intentar desde el detalle
                ok = try_detail_apply_from_hash(hlink)

            if ok:
                postuladas_kw += 1
                max_total_ref[0] += 1
            else:
                print(f"  ↪️ No se pudo postular — {hlink}")

            human_sleep(0.6, 1.2)

        # limpiar la lista ANTES de pasar de página (fiel al algoritmo)
        links.clear()

        if postuladas_kw >= max_kw or max_total_ref[0] >= MAX_TOTAL:
            break

        # pasar de página del portal
        if not goto_next_page():
            break
        pagina += 1

    return postuladas_kw

# ==================== MAIN ====================
def main():
    print("🔎 Iniciando…")
    ensure_logged_in()

    total_ref = [0]  # mutable para pasar por referencia
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
    if KEEP_OPEN_AFTER_RUN:
        print("\n🔒 Dejo Brave abierto para revisar. Presioná Enter acá para cerrar…")
        try: input()
        except KeyboardInterrupt: pass
    try: driver.quit()
    except: pass

if __name__ == "__main__":
    main()

