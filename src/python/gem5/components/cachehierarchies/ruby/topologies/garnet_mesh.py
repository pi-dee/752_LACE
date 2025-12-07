from m5.objects import GarnetNetwork, GarnetRouter, GarnetExtLink, GarnetIntLink, GarnetNetworkInterface
from m5.params import *

class GarnetMesh(GarnetNetwork):
    """
    A Mesh_XY topology compatible with the gem5 Standard Library (stdlib).
    """

    def __init__(self, ruby_system, num_routers=16, num_rows=4):
        super().__init__()
        self.ruby_system = ruby_system
        
        # --- FIX: Use underscore variables for Python-only helper data ---
        self._num_routers = num_routers 
        # Note: self.num_rows IS a valid C++ parameter for GarnetNetwork, 
        # so we keep it without the underscore so the C++ routing logic sees it.
        self.num_rows = num_rows        
        
        # Garnet defaults
        self.ni_flit_size = 16
        self.vcs_per_vnet = 4
        self.buffers_per_data_vc = 4

    def connectControllers(self, controllers):
        """
        Connects the controllers to routers in a Mesh topology.
        """
        # 1. Retrieve the router count from our private variable
        num_routers = int(self._num_routers)
        
        # Calculate rows and columns
        rows = int(self.num_rows)
        cols = int(num_routers / rows)
        link_latency = 3
        
        if cols * rows != num_routers:
             print(f"Warning: Mesh {rows}x{cols} != {num_routers} routers. Layout may be irregular.")

        # 2. Create Routers (Exactly 16 for your case)
        self.routers = [
            GarnetRouter(router_id=i, latency=5) for i in range(num_routers)
        ]

        # 3. Create Network Interfaces and External Links
        self.netifs = []
        self.ext_links = []
        link_count = 0
        
        for i, c in enumerate(controllers):
            # LOGIC: Map controllers to routers using Modulo.
            # 16 Cores example:
            # - L1 Cache 0 (index 0)  -> Router 0
            # - L1 Cache 15 (index 15)-> Router 15
            # - L2 Cache 0 (index 16) -> Router 0 (16 % 16 = 0)
            # - L3 Cache 0 (index 32) -> Router 0 (32 % 16 = 0)
            # This stacks the private L1/L2 and shared L3 slice on the same router (Tile).
            router_id = i % num_routers
            
            # Create NI
            ni = GarnetNetworkInterface(
                id=i,
                vcs_per_vnet=self.vcs_per_vnet,
                virt_nets=self.number_of_virtual_networks
            )
            self.netifs.append(ni)

            # Connect Controller -> Router (via NI)
            # GarnetExtLink connects the Controller (ext_node) to the Router (int_node).
            # The C++ backend automatically inserts the NI in between.
            ext_link = GarnetExtLink(
                link_id=link_count,
                ext_node=c,                  
                int_node=self.routers[router_id], 
                latency=link_latency, 
            )
            self.ext_links.append(ext_link)
            link_count += 1

        # 4. Create Internal Links (Router <-> Router) : Mesh XY Logic
        self.int_links = []
        
        # East -> West
        for row in range(rows):
            for col in range(cols):
                if col + 1 < cols:
                    east_out = col + (row * cols)
                    west_in = (col + 1) + (row * cols)
                    
                    self.int_links.append(GarnetIntLink(
                        link_id=link_count,
                        src_node=self.routers[east_out],
                        dst_node=self.routers[west_in],
                        src_outport="East",
                        dst_inport="West",
                        weight=1,
                        latency=link_latency,
                    ))
                    link_count += 1

        # West -> East
        for row in range(rows):
            for col in range(cols):
                if col + 1 < cols:
                    east_in = col + (row * cols)
                    west_out = (col + 1) + (row * cols)
                    
                    self.int_links.append(GarnetIntLink(
                        link_id=link_count,
                        src_node=self.routers[west_out],
                        dst_node=self.routers[east_in],
                        src_outport="West",
                        dst_inport="East",
                        weight=1,
                        latency=link_latency,
                    ))
                    link_count += 1

        # North -> South
        for col in range(cols):
            for row in range(rows):
                if row + 1 < rows:
                    north_out = col + (row * cols)
                    south_in = col + ((row + 1) * cols)
                    
                    self.int_links.append(GarnetIntLink(
                        link_id=link_count,
                        src_node=self.routers[north_out],
                        dst_node=self.routers[south_in],
                        src_outport="North",
                        dst_inport="South",
                        weight=2,
                        latency=link_latency,
                    ))
                    link_count += 1

        # South -> North
        for col in range(cols):
            for row in range(rows):
                if row + 1 < rows:
                    north_in = col + (row * cols)
                    south_out = col + ((row + 1) * cols)
                    
                    self.int_links.append(GarnetIntLink(
                        link_id=link_count,
                        src_node=self.routers[south_out],
                        dst_node=self.routers[north_in],
                        src_outport="South",
                        dst_inport="North",
                        weight=2,
                        latency=link_latency,
                    ))
                    link_count += 1