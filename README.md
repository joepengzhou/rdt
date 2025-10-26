# RDT Protocol Implementation
Implementation of three reliable data transfer (RDT) protocols 

rdt/
├── channel.py         # Simulate unreliable network
├── gbn.py             # Go-Back-N protocol
├── sr.py              # Selective Repeat protocol
├── tcp_like.py        # TCP-like protocol with RTT estimation
├── experiment.py      # Runs and compares all protocols
├── plots/             # Generated graphs
└── report/            # Final report and presentation


# Install dependencies
pip install -r requirements.txt

# Or using virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt


**Usage Examples**

python3 experiment.py --loss 0.1 --rtt 200 --window 8 --bytes 10000

# Run all scenarios 
python3 experiment.py

# Run specific scenario
python3 experiment.py --scenario medium_loss --runs 5

# Custom output directory
python3 experiment.py --output my_results --scenario high_loss




