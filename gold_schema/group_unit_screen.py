# Groups unit_screen.py's screen-B flags by source, analyte and the two disagreeing packages (median ratio), to tell partial-vs-total method differences from unit errors. Edit the CSV name below.
import csv,collections,statistics,psycopg2
rows=[r for r in csv.DictReader(open('unit_screen_20261107_155211.csv',encoding='utf-8')) if r['screen']=='B']
by=collections.defaultdict(list)
for r in rows: by[(r['source_system'],r['sample_id'],r['analyte'])].append(r)
groups=collections.Counter(); ratio=collections.defaultdict(list)
def ppm(r): v=float(r['value']); u=r['unit']; return v*10000 if u=='%' else v/1000 if u=='ppb' else v
for (src,sid,an),rs in by.items():
    rs=sorted(rs,key=ppm); lo,hi=rs[0],rs[-1]
    key=(src,an,lo['package_id'],lo['unit'],hi['package_id'],hi['unit'])
    groups[key]+=1; ratio[key].append(ppm(hi)/max(ppm(lo),1e-9))
ENV={}
for l in open('../.env',encoding='utf-8'):
    l=l.strip()
    if l and not l.startswith('#') and '=' in l: k,v=l.split('=',1); ENV[k.strip()]=v.strip().strip('"').strip("'")
g=psycopg2.connect(host=ENV["LITHODAT_DB_HOST"],port=ENV["LITHODAT_DB_PORT"],dbname="interzona_cm",user=ENV["LITHODAT_DB_USER"],password=ENV["LITHODAT_DB_PASSWORD"]);c=g.cursor()
pk={int(p) for k in groups for p in (k[2],k[4]) if p}
c.execute("select package_id, package_name from geochem.analytical_packages where package_id = any(%s)",(list(pk),))
name=dict((str(a),b) for a,b in c.fetchall())
for k,n in groups.most_common(45):
    print(f"{n:5d} {k[0][:20]:20s} {k[1]:3s} lo[{k[3]}] {name.get(k[2],k[2])[:42]:42s} | hi[{k[5]}] {name.get(k[4],k[4])[:42]:42s} x{statistics.median(ratio[k]):.0f}")
