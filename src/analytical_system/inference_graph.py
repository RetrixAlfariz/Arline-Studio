class Graph:
    def __init__(self): self.nodes=[]; self.edges=[]; self.n=1
    def add(self,kind,label,confidence,parents=None,source_facts=None,metadata=None):
        i=f'inf_{self.n:04d}'; self.n+=1; node={'id':i,'kind':kind,'label':label,'confidence':round(float(confidence),4),'parents':parents or [],'source_facts':source_facts or [],'metadata':metadata or {}}; self.nodes.append(node)
        for p in node['parents']: self.edges.append({'from':p,'to':i})
        return i
    def dump(self): return {'nodes':self.nodes,'edges':self.edges}
