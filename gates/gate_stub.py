"""Gate interface stub. NOT IMPLEMENTED: every gate raises until built and parity-tested."""
GATES = ["G0","G1","G2","G2F","G3S","G3K","G3","G4a","G4b","G4c","G4d","G5","G6","GP"]

def run_gate(gate_id: str, project_root: str) -> str:
    raise NotImplementedError(f"{gate_id}: NOT IMPLEMENTED")
