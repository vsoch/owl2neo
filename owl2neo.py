from rdflib.serializer import Serializer
from rdflib import Graph as graphrdf, plugin
import rdfextras
import xmltodict
rdfextras.registerplugins()
plugin.register(
    'json-ld',
    Serializer,
    'rdflib_jsonld.serializer',
    'JsonLDSerializer')
import numpy
import json
import re
import os
import sys


def make_gist(owl_file,outfolder="gist",username="vsoch",repo_name="owl2neo"):
    g = graphrdf()
    g.parse(owl_file)
    graph = json.loads(g.serialize(format='json-ld', indent=4))

    # Extract all the "types"
    types = get_types(graph)

    # Generate a number lookup for the node
    lookup = get_node_lookup(graph)

    # Extract nodes and relationships
    nodes,relations = parse_owl(graph,lookup)

    # Save to gist file
    write_gist(owl_file,nodes,relations,outfolder)

    # Save readme
    write_readme(owl_file,username,repo_name,outfolder)

    print "Done parsing owl. Push to github to view."


# create a node
def create_node(nid,node_type,uid,name,properties):
    '''create_node:
    generate text string to generate a neo4j node
    properties: should be list of tuples of form (name,property)
    '''
    node_type = node_type.lower().replace(" ","").replace("'","").replace("-","")
    name = name.replace("'","").replace("-","").encode("utf-8")
    if len(properties) > 0:
        property_string = ""
        for p in range(len(properties)):
            property_name = properties[p][0].lower().replace(" ","").replace("'","").replace("-","")
            property_value = properties[p][1]
            property_string = "%s %s : '%s'," %(property_string,property_name,property_value)
        property_string = property_string[:-1]
        try:
            return "create (_%s:%s { id : '%s', name :'%s', %s})\n" %(nid,node_type,uid,name,property_string.encode("utf-8"))
        except:
            return "create (_%s:%s { id : '%s', name :'%s'})\n" %(nid,node_type,uid,name)
    else:
        return "create (_%s:%s { id : '%s', name :'%s'})\n" %(nid,node_type,uid,name)

# create a relationship
def create_relation(nid1,nid2,relationship):
    relationship = relationship.upper().replace("'","").replace("-","")
    return "create _%s-[:`%s`]->_%s\n" %(nid1,relationship,nid2)


def get_types(graph):
    '''get_types
    will return unique types in an owl graph
    '''
    types = []
    for node in graph:
       if "@type" in node:
           types.append(node["@type"])
    types = numpy.unique(types).tolist()
    return types

    
def get_node_lookup(graph):
    '''get_node_lookup
    generates dictionary to look up node index (number from 1..n) based on URI
    '''
    nodes = dict()
    count = 1
    for node in graph:
        if "@type" in node:  
            if "http://www.w3.org/2002/07/owl#Class" in node["@type"]: 
                node_id = node["@id"].encode("utf-8")
                if node_id not in nodes:
                    nodes[node_id] = count
                    count +=1
    return nodes


def clean_meta(meta):
    '''clean_meta
    make sure encoded in utf-8'
    '''
    cleaned = dict()
    for key,val in meta.iteritems():
        cleaned[key.encode("utf-8")] = val.encode("utf-8")
    return cleaned


def make_properties(meta):
    '''parse dictionary into list of tuples'''
    properties = []
    for key,val in meta.iteritems():
       properties.append([key.encode("utf-8"),val.encode("utf-8")])
    return properties

def parse_owl(graph,lookup):

    # First let's get meta data associated with nodes
    nodes = dict()
    for node in graph:
        if "@type" in node:
            # This is a node
            if "http://www.w3.org/2002/07/owl#Class" in node["@type"]:
                nid = node["@id"]
                fields = [x for x in node.keys() if x not in ["@id"]]
                meta = dict()
                for field in fields:
                    field_entries = node[field]
                    content = ""
                    for entry in field_entries:
                        if "@id" in entry:
                            content = "%s,%s" %(content,entry["@id"])
                        elif "@value" in entry:
                            content = "%s,%s" %(content,entry["@value"])
                        else:
                            content = "%s,%s" %(content,entry)
                    meta[field] = content.strip(",")
                if nid in nodes:
                    holder = nodes[nid]
                    holder.update(meta)
                    nodes[nid] = holder
                else:
                    nodes[nid] = meta

    # Now generate nodes!
    node_list = []
    for node,meta in nodes.iteritems():
        node_type = meta["@type"].split("#")[-1].encode("utf-8")
        # First take the label, then the preferred label
        if "http://www.w3.org/2000/01/rdf-schema#label" in meta:
            label = meta["http://www.w3.org/2000/01/rdf-schema#label"]
        elif "http://www.w3.org/2004/02/skos/core#prefLabel" in meta:
            label = meta["http://www.w3.org/2004/02/skos/core#prefLabel"]
        else:
            label = node
        properties = make_properties(meta)
        uid = lookup[node]
        node_list.append(create_node(node,node_type,uid,label,properties))


    # Now generate relationships (does not include "sublass of"
    relations = []
    for node in graph:
        if "@type" in node:
            # This is a relationship
            if "http://www.w3.org/2002/07/owl#Restriction" in node["@type"]:
                if "http://www.w3.org/2002/07/owl#onProperty" in node:
                    relationship = node["http://www.w3.org/2002/07/owl#onProperty"][0]["@id"]
                    relationship = relationship.split("#")[-1]
                    nid1 = node["@id"]
                    if "http://www.w3.org/2002/07/owl#someValuesFrom" in node:
                        nid2 = node["http://www.w3.org/2002/07/owl#someValuesFrom"][0]["@id"]
                    else:
                        nid2 = node["http://www.w3.org/2002/07/owl#allValuesFrom"][0]["@id"]
                relations.append(create_relation(nid1,nid2,relationship))

    return node_list,relations


def write_gist(owl_file,nodes,relations,outfolder):
    if not os.path.exists(outfolder):
        os.mkdir(outfolder)
    filey = open("%s/graph.gist" %(outfolder),'w')
    filey.writelines("= %s\n:neo4j-version: 2.0.0\n:author: Poldracklab\n:twitter: @vsoch\n:tags: neuroscience:brain:regions:ontology:NIF\n'''\nThis is a neo4j graph to show the NIF brain anatomy ontology from Tom: %s.\n'''\n[source, cypher]\n----\n" %(owl_file,owl_file))
    for node in nodes:
        filey.writelines(node)
    for relation in relations:
        filey.writelines(relation)
    filey.writelines("----\n//graph\nWe can use cypher to query the graph, here are some examples:\n[source, cypher]\n----\nMATCH (c:class)-[l:PROPER_PART_OF]->(d:class) RETURN c as class_one, d as class_two\n----\n//table\n'''\n[source, cypher]\n----\nMATCH (p:peak)-[l:ATLOCATION]->(c:coordinate) RETURN c.name as name, c.coordinatevector as coordinate, p.equivalent_zstatistic as z, p.name as peak_name, p.pvalue_uncorrected as pvalue_uncorrected\n----\n//table\n'''\n== NIF Ontology Base\n* link:https://github.com/SciCrunch/NIF-Ontology/tree/fma/BiomaterialEntities[NIF Biomedical Entities]\n")
    filey.close()


def write_readme(owl_file,username,repo_name,outfolder):
    # Now write a Readme to link the gist
    filey = open("%s/README.md" %(outfolder),'w')
    filey.writelines("### %s\n" %(owl_file))
    filey.writelines("[view graph](http://gist.neo4j.org/?github-"+ username + "%2F" + repo_name + "%2F%2F" + outfolder + "%2Fgraph.gist)\n")
    filey.close()       
