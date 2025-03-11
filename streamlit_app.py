import streamlit as st
import simpy
import random
import pandas as pd
import plotly.express as px
import numpy as np

# --- Version 5: Complete Rewrite for Robustness ---
class Config:
    def __init__(self, cars_per_hour, order_time, prep_time, payment_time, order_queue_capacity, payment_queue_capacity, simulation_time):
        self.CARS_PER_HOUR = cars_per_hour
        self.ORDER_TIME = order_time
        self.PREP_TIME = prep_time
        self.PAYMENT_TIME = payment_time
        self.ORDER_QUEUE_CAPACITY = order_queue_capacity
        self.PAYMENT_QUEUE_CAPACITY = payment_queue_capacity
        self.SIMULATION_TIME = simulation_time

class DriveThrough:
    def __init__(self, env, config):
        self.env = env
        self.config = config
        # Resources with limited capacity (single server for each)
        self.order_station = simpy.Resource(env, capacity=1)
        self.payment_window = simpy.Resource(env, capacity=1)
        self.order_prep_station = simpy.Resource(env, capacity=1) # Renamed for clarity

        # Queues with capacity limits (using simpy.Store for flexibility)
        self.order_queue = simpy.Store(env, capacity=config.ORDER_QUEUE_CAPACITY)
        self.payment_queue = simpy.Store(env, capacity=config.PAYMENT_QUEUE_CAPACITY)

        # Events for order preparation completion
        self.order_ready_events = {}

        # Metrics dictionary - more descriptive names
        self.metrics = {
            'ordering_wait_times': [],
            'payment_wait_times': [],
            'total_service_times': [],
            'cars_completed_service': 0,
            'cars_blocked_at_order_queue': 0,
            'cars_blocked_at_payment_queue': 0,
            'cars_balked_initially': 0,
            'processed_car_ids': [],
            'balking_incidences': [], # To track if balking happened per car
        }

    def car_process(self, car_id):
        """Process for each car going through the drive-through."""
        print(f"Car {car_id} arrived at {self.env.now:.2f}")
        arrival_time = self.env.now
        self.metrics['processed_car_ids'].append(car_id)

        # Initialize metrics for this car
        for metric_key in ['ordering_wait_times', 'payment_wait_times', 'total_service_times']:
            self.metrics[metric_key].append(np.nan) # Initialize as NaN, updated later
        self.metrics['balking_incidences'].append(0) # 0 = no balking (yet)

        # --- Stage 0: Initial Balking Check ---
        combined_queue_length = len(self.order_queue.items) + len(self.payment_queue.items)
        combined_capacity = self.config.ORDER_QUEUE_CAPACITY + self.config.PAYMENT_QUEUE_CAPACITY
        if combined_queue_length >= combined_capacity:
            if random.random() < 0.3: # Balking probability
                print(f"Car {car_id} balked (initial queues full) at {self.env.now:.2f}, Combined Queue Length: {combined_queue_length}, Capacity: {combined_capacity}")
                self.metrics['cars_balked_initially'] += 1
                self.metrics['balking_incidences'][-1] = 1 # Mark balking for this car
                return # Car leaves without service

        # --- Stage 1: Enter Order Queue ---
        order_queue_entry_time = self.env.now
        if len(self.order_queue.items) >= self.config.ORDER_QUEUE_CAPACITY:
            print(f"Car {car_id} BLOCKED at order queue (full) at {self.env.now:.2f}, Order Queue Length: {len(self.order_queue.items)}, Capacity: {self.config.ORDER_QUEUE_CAPACITY}")
            self.metrics['cars_blocked_at_order_queue'] += 1
            return # Car blocked, leaves system from order queue entry
        else:
            yield self.order_queue.put(car_id) # Enter the order queue
            self.metrics['ordering_wait_times'][-1] = self.env.now - order_queue_entry_time # Record wait time in queue
            print(f"Car {car_id} entered order queue at {self.env.now:.2f}, Order Queue Length: {len(self.order_queue.items)}")

        # --- Stage 2: Ordering at Station ---
        with self.order_station.request() as order_req:
            yield order_req # Request ordering station
            yield self.order_queue.get() # "Get" the car from the order queue (FIFO)
            print(f"Car {car_id} started ordering at {self.env.now:.2f}")
            order_start_time = self.env.now
            order_duration = random.uniform(0.9, 1.1) * self.config.ORDER_TIME
            yield self.env.timeout(order_duration) # Ordering process
            print(f"Car {car_id} finished ordering at {self.env.now:.2f}")

        # Order preparation process (runs in parallel)
        self.env.process(self.prepare_order(car_id, car_id)) # Pass order details if needed

        # --- Stage 3: Enter Payment Queue ---
        payment_queue_entry_time = self.env.now
        if len(self.payment_queue.items) >= self.config.PAYMENT_QUEUE_CAPACITY:
            print(f"Car {car_id} BLOCKED at payment queue (full) at {self.env.now:.2f}, Payment Queue Length: {len(self.payment_queue.items)}, Capacity: {self.config.PAYMENT_QUEUE_CAPACITY}")
            self.metrics['cars_blocked_at_payment_queue'] += 1
            yield self.payment_queue.cancel(car_id) # IMPORTANT: Cancel put event for Store queue blocking
            return # Car blocked, leaves system from payment queue entry
        else:
            yield self.payment_queue.put(car_id) # Enter payment queue
            self.metrics['payment_wait_times'][-1] = self.env.now - payment_queue_entry_time # Record wait time
            print(f"Car {car_id} entered payment queue at {self.env.now:.2f}, Payment Queue Length: {len(self.payment_queue.items)}")

        # --- Stage 4: Payment and Pickup at Window ---
        with self.payment_window.request() as payment_req:
            yield payment_req # Request payment window
            yield self.payment_queue.get() # Get car from payment queue
            print(f"Car {car_id} started payment at {self.env.now:.2f}")
            payment_start_time = self.env.now
            payment_duration = random.uniform(0.9, 1.1) * self.config.PAYMENT_TIME
            yield self.env.timeout(payment_duration) # Payment process
            print(f"Car {car_id} finished payment at {self.env.now:.2f}")

        # --- Stage 5: Wait for Order Prep Completion ---
        yield self.order_ready_events[car_id] # Wait for the 'order ready' event to be triggered
        del self.order_ready_events[car_id] # Clean up event
        print(f"Car {car_id} order ready for pickup at {self.env.now:.2f}")

        # --- Stage 6: Service Completion ---
        self.metrics['total_service_times'][-1] = self.env.now - arrival_time # Record total time
        self.metrics['cars_completed_service'] += 1
        print(f"Car {car_id} completed service at {self.env.now:.2f}")


    def prepare_order(self, car_id, order):
        """Simulates order preparation."""
        with self.order_prep_station.request() as prep_req: # Request order prep station
            yield prep_req
            print(f"Order preparation started for car {car_id} at {self.env.now:.2f}")
            prep_duration = random.uniform(0.8, 1.2) * self.config.PREP_TIME
            yield self.env.timeout(prep_duration) # Order prep time
            print(f"Order preparation finished for car {car_id} at {self.env.now:.2f}")
            self.order_ready_events[car_id].succeed() # Trigger 'order ready' event

    def car_arrival_process(self):
        """Generates car arrivals based on CARS_PER_HOUR."""
        car_id = 0
        while True:
            car_id += 1
            self.order_ready_events[car_id] = self.env.event() # Create event for order ready
            self.env.process(self.car_process(car_id)) # Start car's process
            arrival_interval = 3600 / self.config.CARS_PER_HOUR # Time between car arrivals
            yield self.env.timeout(arrival_interval)

def run_simulation(config):
    """Runs the drive-through simulation with the given configuration."""
    print("\n--- Starting Simulation ---")
    print("Simulation Parameters:")
    for param, value in config.__dict__.items():
        print(f"  {param}: {value}")
    env = simpy.Environment()
    drive_through = DriveThrough(env, config)
    env.process(drive_through.car_arrival_process()) # Start car arrivals
    env.run(until=config.SIMULATION_TIME) # Run simulation for specified time
    print("--- Simulation Completed ---\n")
    return drive_through.metrics

def analyze_results(metrics, config):
    """Analyzes simulation metrics and generates results."""
    if not metrics['processed_car_ids']: # No cars processed
        return { # Return default empty results
            'Cars Served': 0,
            'Cars Blocked (Order Queue)': 0,
            'Cars Blocked (Payment Queue)': 0,
            'Cars Balked (Initial)': 0,
            'Throughput (cars/hour)': 0.0,
            'Avg Wait Ordering Queue (min)': 0.0,
            'Avg Wait Payment Queue (min)': 0.0,
            'Avg Total Time (min)': 0.0,
        }, px.histogram(title='Distribution of Wait Times at Order Queue'), px.histogram(title='Distribution of Wait Times at Payment Queue'),px.histogram(title='Distribution of Total Time in System'), pd.DataFrame()

    df_metrics = pd.DataFrame({ # Create DataFrame for analysis
        'Car ID': metrics['processed_car_ids'],
        'Wait Time Ordering Queue (min)': metrics['ordering_wait_times'],
        'Wait Time Payment Queue (min)': metrics['payment_wait_times'],
        'Total Time (min)': metrics['total_service_times'],
        'Balked Initially': [bool(balk) for balk in metrics['balking_incidences']] # Convert to boolean for clarity
    })

    avg_wait_ordering = df_metrics['Wait Time Ordering Queue (min)'].mean()
    avg_wait_payment = df_metrics['Wait Time Payment Queue (min)'].mean()
    avg_total_time = df_metrics['Total Time (min)'].mean()
    throughput = metrics['cars_completed_service'] / config.SIMULATION_TIME * 60 # cars per hour

    summary_results = { # Create summary results dictionary
        'Cars Served': metrics['cars_completed_service'],
        'Cars Blocked (Order Queue)': metrics['cars_blocked_at_order_queue'],
        'Cars Blocked (Payment Queue)': metrics['cars_blocked_at_payment_queue'],
        'Cars Balked (Initial)': metrics['cars_balked_initially'],
        'Throughput (cars/hour)': f"{throughput:.2f}",
        'Avg Wait Ordering Queue (min)': f"{avg_wait_ordering:.2f}",
        'Avg Wait Payment Queue (min)': f"{avg_wait_payment:.2f}",
        'Avg Total Time (min)': f"{avg_total_time:.2f}",
    }

    # Create histograms for visualization
    fig_wait_order_queue = px.histogram(df_metrics, x='Wait Time Ordering Queue (min)', nbins=20, title='Distribution of Wait Times at Order Queue')
    fig_wait_payment_queue = px.histogram(df_metrics, x='Wait Time Payment Queue (min)', nbins=20, title='Distribution of Wait Times at Payment Queue')
    fig_total_time = px.histogram(df_metrics, x='Total Time (min)', nbins=20, title='Distribution of Total Time in System')

    return summary_results, fig_wait_order_queue, fig_wait_payment_queue, fig_total_time, df_metrics

# --- Streamlit App (Modified for Parameter Update Debugging) ---
st.set_page_config(page_title="Robust Drive-Through Simulation", page_icon=":car:", layout="wide")
st.title("Robust Drive-Through Simulation (Parameter Update DEBUG)") # Updated title
st.write("""
This app simulates a drive-through service. **We are currently DEBUGGING parameter updates.**
Adjust parameters in the sidebar and click 'Run Simulation'. **Check below if parameters are updated correctly.**
""") # Modified description

# --- Sidebar for Inputs ---
with st.sidebar:
    st.header("Simulation Parameters")

    # Initialize session state for parameters (if not already initialized)
    if 'cars_per_hour' not in st.session_state: st.session_state.cars_per_hour = 70.0
    if 'order_time' not in st.session_state: st.session_state.order_time = 1.2
    if 'prep_time' not in st.session_state: st.session_state.prep_time = 2.00
    if 'payment_time' not in st.session_state: st.session_state.payment_time = 0.8
    if 'order_queue_capacity' not in st.session_state: st.session_state.order_queue_capacity = 15
    if 'payment_queue_capacity' not in st.session_state: st.session_state.payment_queue_capacity = 2
    if 'simulation_time' not in st.session_state: st.session_state.simulation_time = 60

    # Input widgets, bind to session state
    cars_per_hour = st.number_input("Cars per Hour", min_value=1.0, max_value=200.0, value=st.session_state.cars_per_hour, step=1.0, format="%.1f", key="cars_per_hour_input")
    order_time = st.number_input("Order Time (min)", min_value=0.1, max_value=10.0, value=st.session_state.order_time, step=0.1, format="%.1f", key="order_time_input")
    prep_time = st.number_input("Preparation Time (min)", min_value=0.1, max_value=20.0, value=st.session_state.prep_time, step=0.1, format="%.2f", key="prep_time_input")
    payment_time = st.number_input("Payment Time (min)", min_value=0.1, max_value=5.0, value=st.session_state.payment_time, step=0.1, format="%.1f", key="payment_time_input")
    order_queue_capacity = st.number_input("Order Queue Capacity", min_value=1, max_value=100, value=st.session_state.order_queue_capacity, step=1, key="order_queue_capacity_input")
    payment_queue_capacity = st.number_input("Payment Queue Capacity", min_value=1, max_value=100, value=st.session_state.payment_queue_capacity, step=1, key="payment_queue_capacity_input")
    simulation_time = st.number_input("Simulation Time (min)", min_value=1, max_value=1440, value=st.session_state.simulation_time, step=1, key="simulation_time_input")

    run_button = st.button("Run Simulation") # Store button in a variable

# --- Main area for Parameter Display and Results ---
st.header("Current Simulation Parameters (for DEBUG)") # New section to display parameters

# Display parameters from session state in the main app area - DEBUGGING
st.write("Parameters being used for simulation (taken from session state):")
st.write(f"- Cars per Hour: {st.session_state.cars_per_hour}")
st.write(f"- Order Time (min): {st.session_state.order_time}")
st.write(f"- Prep Time (min): {st.session_state.prep_time}")
st.write(f"- Payment Time (min): {st.session_state.payment_time}")
st.write(f"- Order Queue Capacity: {st.session_state.order_queue_capacity}")
st.write(f"- Payment Queue Capacity: {st.session_state.payment_queue_capacity}")
st.write(f"- Simulation Time (min): {st.session_state.simulation_time}")

st.header("Simulation Results") # Results section as before

if run_button: # Check if the button is clicked
    # **Explicitly get values from session state RIGHT BEFORE creating Config**
    config = Config(
        cars_per_hour = st.session_state.cars_per_hour,
        order_time = st.session_state.order_time,
        prep_time = st.session_state.prep_time,
        payment_time = st.session_state.payment_time,
        order_queue_capacity = st.session_state.order_queue_capacity,
        payment_queue_capacity = st.session_state.payment_queue_capacity,
        simulation_time = st.session_state.simulation_time
    )
    metrics = run_simulation(config)
    results, fig_wait_order_queue, fig_wait_payment_queue, fig_total_time, df_results = analyze_results(metrics, config)

    if 'df_results' in locals():
        st.dataframe(df_results)

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Cars Served", results['Cars Served'])
            st.metric("Blocked Order Queue", results['Cars Blocked (Order Queue)'])
            st.metric("Blocked Payment Queue", results['Cars Blocked (Payment Queue)'])
            st.metric("Balked (Initial)", results['Cars Balked (Initial)'])
        with col2:
            st.metric("Throughput (cars/hour)", results['Throughput (cars/hour)'])
            st.metric("Avg Order Wait (min)", results['Avg Wait Ordering Queue (min)'])
        with col3:
            st.metric("Avg Payment Wait (min)", results['Avg Wait Payment Queue (min)'])
        with col4:
            st.metric("Avg Total Time (min)", results['Avg Total Time (min)'])

        st.plotly_chart(fig_wait_order_queue, use_container_width=True)
        st.plotly_chart(fig_wait_payment_queue, use_container_width=True)
        st.plotly_chart(fig_total_time, use_container_width=True)
    else:
        st.warning("No cars were served in this simulation run. Adjust parameters and re-run.")
else:
    st.info("Set simulation parameters in the sidebar and click 'Run Simulation' to see results.")
