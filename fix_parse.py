# Read pulse.py, fix the JSON parsing, write it back
with open("/root/clearfolks/pulse.py", "r") as f:
    content = f.read()

old = '        return json.loads(raw)'
new = '        clean = raw.replace("```json", "").replace("```", "").strip()\n        return json.loads(clean)'

content = content.replace(old, new)

with open("/root/clearfolks/pulse.py", "w") as f:
    f.write(content)

print("Fixed. Verifying...")
# Show the analyze_signals function
start = content.find("def analyze_signals")
print(content[start:start+400])
