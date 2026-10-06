import asyncio
from playwright.async_api import async_playwright

async def inspect():
    async with async_playwright() as p:
        b = await p.chromium.connect_over_cdp('http://127.0.0.1:9222')
        context = b.contexts[0]
        li_page = next((pg for pg in context.pages if 'linkedin.com' in pg.url), None)
        if not li_page:
            print("No LinkedIn page")
            return
            
        posts = await li_page.evaluate("""() => {
            const items = Array.from(document.querySelectorAll("div[role='listitem'], li[role='listitem'], [role='listitem']"));
            return items.map((item, idx) => {
                const text = (item.innerText || '').trim();
                const moreBtn = Array.from(item.querySelectorAll("button, span")).find(b => {
                    const t = (b.innerText || '').trim().toLowerCase();
                    return t === 'more' || t === '… more' || t === '... more' || t === 'see more';
                });
                return {
                    idx: idx,
                    textLen: text.length,
                    hasMoreBtn: !!moreBtn,
                    preview: text.slice(0, 120).replace(/\\n/g, ' ')
                };
            }).filter(x => x.textLen > 40);
        }""")
        print(f"Total listitem posts found: {len(posts)}")
        for p in posts[:8]:
            print(p)

if __name__ == '__main__':
    asyncio.run(inspect())
