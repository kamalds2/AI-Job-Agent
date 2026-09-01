import httpx

land_url = "https://www.adzuna.in/land/ad/5861220960?aztt=eyJhbGciOiJIUzI1NiJ9.eyJ0cyI6IjNhMGE0M2M0IiwidHQiOiJhcGkiLCJjaSI6IjNLZkZkTWlqOFJHSVl2VUJxN1V1TGciLCJleHAiOjE3ODg2MjY0NzcsImlhdCI6MTc4ODAyMTY3N30.hHtd2pmjYor1ejY2MKcDfNFS01Xctk8uzapv_wWyhXY&from_adp=1&v=A9CC7C056478F0E56B9CF479B7410FF753F882D8&se="
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
try:
    r = httpx.get(land_url, headers=headers, follow_redirects=True, timeout=15)
    print("Redirect Status:", r.status_code)
    print("Final Redirected Destination URL:", r.url)
except Exception as e:
    print("Error:", e)
