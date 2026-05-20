import os, json, urllib.request, xml.etree.ElementTree as ET
import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

SIGNAL_PROMPT = """You are Pulse, a buying signal analyst for Clearfolks Templates — a store selling practical digital organizer tools for caregivers and families on Etsy.

Products available:
- Caregiver Organizer App (for family caregivers managing medications, appointments, care notes)
- Etsy Seller Organizer App (for Etsy sellers managing orders, inventory, finances)

You will receive Reddit posts. Identify HIGH-INTENT buying signals — people who are overwhelmed, actively looking for a system, just started caregiving, or frustrated with disorganization.

For each genuine buying signal, output a JSON object. Output a JSON array only. No text outside the array. If no signals, output [].

Each object:
{
  "signal_id": "S1",
  "subreddit": "r/subreddit",
  "post_title": "exact title",
  "post_url": "url",
  "signal_quote": "key phrase",
  "pain_point": "one sentence",
  "product_match": "Caregiver Organizer App or Etsy Seller Organizer App",
  "score": 7,
  "suggested_response": "helpful reply mentioning product naturally"
}

Only include posts scoring 6 or above."""

# Test with just 5 posts from caregivers
url = "https://www.reddit.com/r/caregivers/new/.rss?limit=5"
req = urllib.request.Request(url, headers={"User-Agent": "ClearfolksBot/1.0"})
with urllib.request.urlopen(req, timeout=10) as resp:
    xml_text = resp.read().decode("utf-8")

root = ET.fromstring(xml_text)
ns = {"atom": "http://www.w3.org/2005/Atom"}
posts = []
for entry in root.findall("atom:entry", ns):
    title = entry.find("atom:title", ns)
    link = entry.find("atom:link", ns)
    posts.append({
        "subreddit": "r/caregivers",
        "title": title.text if title is not None else "",
        "url": link.get("href") if link is not None else "",
    })

print(f"Posts fetched: {len(posts)}")

message = client.messages.create(
    model="claude-haiku-4-5",
    max_tokens=2000,
    messages=[{"role": "user", "content": f"{SIGNAL_PROMPT}\n\nPosts:\n{json.dumps(posts, indent=2)}"}]
)

raw = message.content[0].text.strip()
print("=== RAW CLAUDE RESPONSE ===")
print(raw)
print("=== END ===")
