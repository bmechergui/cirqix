import os
import sys
import subprocess
import time

# Ensure playwright is installed
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Playwright not found. Installing playwright via pip...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])
    print("Installing chromium browser...")
    subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
    from playwright.sync_api import sync_playwright

print("Playwright is ready. Starting screenshots generation...")

brain_dir = r"C:\Users\Mechegui\.gemini\antigravity\brain\996e9129-88ab-496a-a7ed-a604a592fa03"
os.makedirs(brain_dir, exist_ok=True)

with sync_playwright() as p:
    print("Launching Chromium headless...")
    browser = p.chromium.launch(headless=True)
    
    # 1440x900 viewport
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    
    # Enable console logging for debugging
    page.on("console", lambda msg: print(f"Browser console: {msg.text}"))
    
    # Login sequence
    print("Navigating to http://localhost:3333/login...")
    page.goto("http://localhost:3333/login")
    time.sleep(2.5)
    print("Filling in login credentials...")
    page.fill("input[type='email']", "test_dev_agent@layrix.ai")
    page.fill("input[type='password']", "Password123!")
    page.click("button[type='submit']")
    time.sleep(3.5)
    print("Logged in successfully. Current URL:", page.url)

    # 1. Dashboard View
    print("Navigating to http://localhost:3333/dashboard...")
    page.goto("http://localhost:3333/dashboard", wait_until="networkidle")
    time.sleep(3) # Let everything load and settle
    
    dashboard_path = os.path.join(brain_dir, "test_dashboard.png")
    page.screenshot(path=dashboard_path)
    print(f"Captured dashboard screenshot to: {dashboard_path}")
    
    # 2. Enter workspace (click the first project)
    # Let's find any project link or card and click it.
    print("Searching for project link to click...")
    
    # Print links present on page for debugging
    links = page.evaluate("() => Array.from(document.querySelectorAll('a')).map(a => ({href: a.href, text: a.innerText}))")
    print(f"Links found on dashboard: {links}")
    
    # Find a project link. Typically they might have /dashboard/projects/ in href or something.
    project_link = None
    for link in links:
        if "/dashboard/projects/" in link['href'] or "project" in link['href'].lower() or "workspace" in link['href'].lower():
            project_link = link['href']
            break
            
    if not project_link and len(links) > 0:
        # Fallback: click first link that goes to /dashboard/... and isn't dashboard itself
        for link in links:
            if "/dashboard" in link['href'] and link['href'] != "http://localhost:3333/dashboard":
                project_link = link['href']
                break

    if project_link:
        print(f"Navigating directly to project URL: {project_link}")
        page.goto(project_link, wait_until="networkidle")
    else:
        # Try to locate card and click
        print("Clicking first project card/link by DOM...")
        page.locator("a[href*='/dashboard/projects/']").first.click()
        page.wait_for_load_state("networkidle")
        
    time.sleep(4) # Wait for project workspace to load fully
    
    # 2. Idea view
    # By default, when loading, the selected stage might be IDEA or we can click it.
    # Let's locate the 'Idea' tab/timeline node.
    # The timeline has buttons/tabs for IDEA, SCHEMA, ERC, PLACEMENT, ROUTING, DRC, EXPORT.
    # Let's click the "Idea" button in timeline.
    print("Locating and clicking 'Idea' stage...")
    page.evaluate("() => { const el = Array.from(document.querySelectorAll('button, div')).find(e => e.innerText && e.innerText.trim().toUpperCase() === 'IDEA'); if(el) el.click(); }")
    time.sleep(2)
    idea_path = os.path.join(brain_dir, "test_idea.png")
    page.screenshot(path=idea_path)
    print(f"Captured idea view screenshot to: {idea_path}")
    
    # 3. Schema view - logical mode
    print("Locating and clicking 'Schema' or 'Schematic' stage...")
    page.evaluate("() => { const el = Array.from(document.querySelectorAll('button, div')).find(e => e.innerText && (e.innerText.trim().toUpperCase() === 'SCHEMA' || e.innerText.trim().toUpperCase() === 'SCHEMATIC')); if(el) el.click(); }")
    time.sleep(2)
    # Ensure logical mode (spec mode) is active by clicking 'Diagram' tab or 'Logical' view switch if needed.
    page.evaluate("() => { const el = Array.from(document.querySelectorAll('button')).find(e => e.innerText && e.innerText.trim().toUpperCase() === 'DIAGRAM'); if(el) el.click(); }")
    # Also make sure ViewModeSwitch is set to Spec/Logical
    page.evaluate("() => { const el = Array.from(document.querySelectorAll('button')).find(e => e.innerText && e.innerText.trim().toUpperCase() === 'LOGICAL'); if(el) el.click(); }")
    time.sleep(2)
    
    schema_path = os.path.join(brain_dir, "test_schema.png")
    page.screenshot(path=schema_path)
    print(f"Captured schema view (logical) screenshot to: {schema_path}")
    
    # 4. ERC view
    print("Locating and clicking 'ERC' stage...")
    page.evaluate("() => { const el = Array.from(document.querySelectorAll('button, div')).find(e => e.innerText && e.innerText.trim().toUpperCase() === 'ERC'); if(el) el.click(); }")
    time.sleep(2)
    erc_path = os.path.join(brain_dir, "test_erc.png")
    page.screenshot(path=erc_path)
    print(f"Captured ERC view screenshot to: {erc_path}")
    
    # 5. Place Green theme
    print("Locating and clicking 'Place' or 'Placement' stage...")
    page.evaluate("() => { const el = Array.from(document.querySelectorAll('button, div')).find(e => e.innerText && (e.innerText.trim().toUpperCase() === 'PLACE' || e.innerText.trim().toUpperCase() === 'PLACEMENT' || e.innerText.trim().toUpperCase() === 'COMPONENT PLACEMENT')); if(el) el.click(); }")
    time.sleep(2)
    
    # Ensure logical mode (spec mode)
    page.evaluate("() => { const el = Array.from(document.querySelectorAll('button')).find(e => e.innerText && e.innerText.trim().toUpperCase() === 'LOGICAL'); if(el) el.click(); }")
    # Ensure Board tab is active
    page.evaluate("() => { const el = Array.from(document.querySelectorAll('button')).find(e => e.innerText && e.innerText.trim().toUpperCase() === 'BOARD'); if(el) el.click(); }")
    
    # Let's find the solder mask color buttons. They are small buttons styled with maskTheme.
    # In PcbView.tsx: title={`Solder Mask: ${SOLDER_MASKS[themeName].name}`}
    # Let's click Green theme (Classic Green)
    print("Clicking Green solder mask...")
    page.evaluate("() => { const el = document.querySelector('button[title*=\"Classic Green\"]'); if(el) el.click(); }")
    time.sleep(1.5)
    green_path = os.path.join(brain_dir, "test_place_green.png")
    page.screenshot(path=green_path)
    print(f"Captured place green screenshot to: {green_path}")
    
    # 6. Place Black theme
    print("Clicking Black solder mask...")
    page.evaluate("() => { const el = document.querySelector('button[title*=\"Matte Black\"]'); if(el) el.click(); }")
    time.sleep(1.5)
    black_path = os.path.join(brain_dir, "test_place_black.png")
    page.screenshot(path=black_path)
    print(f"Captured place black screenshot to: {black_path}")
    
    # 7. Place Blue theme
    print("Clicking Blue solder mask...")
    page.evaluate("() => { const el = document.querySelector('button[title*=\"Classic Blue\"]'); if(el) el.click(); }")
    time.sleep(1.5)
    blue_path = os.path.join(brain_dir, "test_place_blue.png")
    page.screenshot(path=blue_path)
    print(f"Captured place blue screenshot to: {blue_path}")
    
    # 8. Place Purple theme
    print("Clicking Purple solder mask...")
    page.evaluate("() => { const el = document.querySelector('button[title*=\"Maker Purple\"]'); if(el) el.click(); }")
    time.sleep(1.5)
    purple_path = os.path.join(brain_dir, "test_place_purple.png")
    page.screenshot(path=purple_path)
    print(f"Captured place purple screenshot to: {purple_path}")
    
    # 9. Place Native theme
    print("Clicking Native mode switch/button...")
    page.evaluate("() => { const el = Array.from(document.querySelectorAll('button')).find(e => e.innerText && e.innerText.trim().toUpperCase() === 'NATIVE'); if(el) el.click(); }")
    time.sleep(3) # Allow KiCanvas to load schematic/PCB file
    native_path = os.path.join(brain_dir, "test_place_native.png")
    page.screenshot(path=native_path)
    print(f"Captured place native screenshot to: {native_path}")

print("All screenshots generated successfully!")
