from tools import Tools

t = Tools("2026-03")

print("\nTOP 20")
print(t.get_top20_month()[:3])

print("\nTOP 100")
print(t.get_top100_last12()[:3])

print("\nPERSONALISED COMPARISON")
print(t.compare("2026-03", "personalised"))

print("\nTITLE TERMS")
print(t.title_terms("top20", "2026-03"))
