import asyncio, httpx, sys
sys.path.insert(0, "c:\\kamal\\AI-Job-Agent")

async def test():
    async with httpx.AsyncClient(verify=False, timeout=15, follow_redirects=True) as c:
        tests = [
            # Cutshort - India tech jobs
            ("Cutshort", "GET", "https://cutshort.io/api/v1/jobs?skip=0&limit=10&location=India"),
            # Instahyre - India tech
            ("Instahyre", "GET", "https://www.instahyre.com/api/v1/opportunity/?format=json&limit=10"),
            # Jobspikr public
            ("ApnaTime", "GET", "https://www.apna.co/jobs/all"),
            # iimjobs - India senior roles
            ("iimjobs", "GET", "https://www.iimjobs.com/j/technology-it-software-jobs-1-1-0.html"),
            # foundit (formerly Monster India) - has RSS
            ("Foundit RSS", "GET", "https://www.foundit.in/rss/search?q=java+backend&loc=India&expfm=3&expto=8"),
            # shine.com
            ("Shine RSS", "GET", "https://www.shine.com/rss/it-software-jobs/"),
        ]
        for name, method, url in tests:
            try:
                r = await c.get(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json, text/html"})
                print(f"{name}: {r.status_code} - len={len(r.text)} - type={r.headers.get('content-type','')[:30]}")
                if r.status_code == 200:
                    text = r.text
                    if "<item>" in text:
                        import re
                        items = re.findall(r"<item>", text)
                        print(f"  RSS items: {len(items)}")
                    elif r.headers.get("content-type","").startswith("application/json"):
                        import json
                        data = r.json()
                        print(f"  JSON keys: {list(data.keys())[:5] if isinstance(data, dict) else f'array[{len(data)}]'}")
            except Exception as e:
                print(f"{name}: ERROR {str(e)[:50]}")

asyncio.run(test())
