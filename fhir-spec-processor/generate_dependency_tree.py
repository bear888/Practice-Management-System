import os
import re
import json
import csv
from collections import defaultdict
from graphlib import TopologicalSorter

# Based on FHIR documentation and observed types in the graphql files.
SCALAR_TYPES = {
    'ID', 'String', 'Boolean', 'uri', 'code', 'markdown', 'instant',
    'positiveInt', 'dateTime', 'Int', 'Float', 'date', 'base64Binary',
    'canonical', 'oid', 'time', 'unsignedInt', 'url', 'uuid', 'xhtml',
    'decimal'
}

def get_defined_types(content):
    """Finds all type and interface names defined in the content."""
    return re.findall(r'(?:type|interface)\s+([A-Z][a-zA-Z0-9_]+)', content)

def get_main_resource_name(content, filename):
    """Heuristically finds the main resource name in a .graphql file."""
    for interface in ['IDomainResource', 'IResource']:
        match = re.search(rf'type\s+([A-Z][a-zA-Z0-9_]+)\s*implements\s*.*?{interface}', content)
        if match:
            return match.group(1)
    match = re.search(r'type\s+([A-Z][a-zA-Z0-9_]+)', content)
    if match:
        return match.group(1)
    return filename.split('.')[0].capitalize()

def get_dependencies_from_content(content):
    """Extracts all potential dependencies from the content of a .graphql file."""
    dependencies = set()
    type_definitions = re.findall(r'(?:type|interface)\s+[A-Za-z0-9_]+\s*(?:implements\s*.*?)*\s*\{([^}]+)\}', content, re.DOTALL)
    for type_def in type_definitions:
        field_types = re.findall(r':\s*\[?([A-Z][a-zA-Z0-9_]+)', type_def)
        for ftype in field_types:
            dependencies.add(ftype)
    return dependencies

def main():
    spec_dir = 'fhir-spec'
    output_csv = 'fhir-spec-processor/dependency_tree.csv'
    output_json = 'fhir-spec-processor/dependency_tree.json'

    file_data = {}
    graphql_files = [f for f in os.listdir(spec_dir) if f.endswith('.graphql')]

    type_to_resource_map = {}
    for filename in graphql_files:
        file_path = os.path.join(spec_dir, filename)
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        main_resource = get_main_resource_name(content, filename)
        defined_types = get_defined_types(content)
        raw_deps = get_dependencies_from_content(content)
        file_data[main_resource] = {'raw_deps': raw_deps}
        for t in defined_types:
            type_to_resource_map[t] = main_resource

    dependency_map = defaultdict(set)
    for resource, data in file_data.items():
        for dep in data['raw_deps']:
            if dep in SCALAR_TYPES or dep == resource:
                continue

            # A dependency is considered external if it's not defined within the
            # scope of the current resource's file. This correctly handles
            # globally defined types like 'HumanName' or 'Identifier'.
            if type_to_resource_map.get(dep) != resource:
                dependency_map[resource].add(dep)

    graph = {resource: list(deps) for resource, deps in dependency_map.items()}
    ts = TopologicalSorter(graph)
    ts.prepare()

    print(f"Generating CSV output at {output_csv}...")
    with open(output_csv, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Level', 'Resource', 'Dependencies'])
        level = 0
        while ts.is_active():
            ready_nodes = sorted(list(ts.get_ready()))
            if not ready_nodes:
                print("Error: Cycle detected in dependencies.")
                break
            for node in ready_nodes:
                dependencies = sorted(list(dependency_map.get(node, [])))
                writer.writerow([level, node, ', '.join(dependencies)])
                ts.done(node)
            level += 1
    print("CSV generation complete.")

    # --- JSON Tree Generation ---
    all_dependencies = set(dep for deps in dependency_map.values() for dep in deps)
    root_nodes = set(dependency_map.keys()) - all_dependencies

    memo = {}
    def build_node(resource_name):
        if resource_name in memo:
            return memo[resource_name]
        node = {"name": resource_name}
        dependencies = sorted(list(dependency_map.get(resource_name, [])))
        if dependencies:
            node["children"] = [build_node(dep) for dep in dependencies]
        memo[resource_name] = node
        return node

    json_tree = [build_node(root) for root in sorted(list(root_nodes))]

    print(f"Generating JSON output at {output_json}...")
    with open(output_json, 'w', encoding='utf-8') as jsonfile:
        json.dump(json_tree, jsonfile, indent=2)
    print("JSON generation complete.")

if __name__ == '__main__':
    main()
