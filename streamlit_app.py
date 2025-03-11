import streamlit as st
import simpy
import random
import pandas as pd
import plotly.express as px
import numpy as np

# --- Simplified Simulation Code ---
class Config:
    def __init__(self, cars_per_hour, order_time, prep_time, payment_time, order_queue_capacity, payment_queue_capacity, simulation_time):
        self.CARS_PER_HOUR = cars_per_hour
        self.ORDER_TIME = order_time
        self.PREP_TIME = prep_time
        self.PAYMENT_TIME = payment_time
        self.ORDER_QUEUE_CAPACITY = order_queue_capacity
        self.PAYMENT_QUEUE_CAPACITY = payment_queue_capacity # Renamed from SERVICE_QUEUE_CAPACITY to PAYMENT_QUEUE_CAPACITY for clarity
        self.SIMULATION_TIME = simulation_time

class DriveThrough:
    def __init__(self, env, config):
        self.env = env
        self.config = config
        self.order_station = simpy.Resource(env, capacity=1) # Single order station
        self.payment_window = simpy.Resource(env, capacity=1) # Single payment window
        self.order_queue = simpy.Store(env, capacity=config.ORDER_QUEUE_CAPACITY)
        self.payment_queue = simpy.Store(env, capacity=config.PAYMENT_QUEUE_CAPACITY) # Renamed for clarity
        self.order_prep = simpy.Resource(env, capacity=1)
        self.order_ready_events = {}
        self.metrics = {
            'wait_times_ordering_queue': [], # Time queuing to menu
            'wait_times_payment_queue': [],  # Time queuing to payment window
            'total_times': [],              # Total time in system
            'cars_served': 0,
            'cars_blocked_payment_queue': 0, # Cars blocked from payment queue
            'car_ids': [],
            'balking_events': [],
        }

    def process_car(self, car_id):
        print(f"Car {car_id} arrived at {self.env.now}")
        arrival_time = self.env.now
        self.metrics['car_ids'].append(car_id)

        # Initialize metrics with NaN
        for metric in ['wait_times_ordering_queue', 'wait_times_payment_queue', 'total_times']:
            self.metrics[metric].append(np.nan)
        self.metrics['balking_events'].append(0)

        # --- Stage 0: Balking (Initial Queue Check) ---
        if len(self.order_queue.items) + len(self.payment_queue.items) >= self.config.ORDER_QUEUE_CAPACITY + self.config.PAYMENT_QUEUE_CAPACITY: # Adjusted for payment queue name
            if random.random() < 0.3: # Keep balking probability for simplicity
                print(f"Car {car_id} balked (initial) at {self.env.now}")
                self.metrics['cars_blocked_payment_queue'] += 1 # Though technically blocked from order queue initially due to total queue length, using payment queue blocked for simplicity in simplified version as it represents overall system pressure. Can adjust to track order queue blocking separately if needed.
                self.metrics['balking_events'][-1] = 1
                return

        # --- Stage 1: Order Queue ---
        enter_order_queue_time = self.env.now
        try:
            yield self.order_queue.put(car_id)
            self.metrics['wait_times_ordering_queue'][-1] = self.env.now - enter_order_queue_time
            print(f"Car {car_id} entered order queue at {self.env.now}")

            # --- Stage 2: Ordering ---
            with self.order_station.request() as request:
                yield request
                yield self.order_queue.get()
                print(f"Car {car_id} began ordering at {self.env.now}")
                order_start_time = self.env.now

                order_time = self.config.ORDER_TIME * random.uniform(0.9, 1.1) # Variable order time
                yield self.env.timeout(order_time)
                print(f"Car {car_id} finished ordering at {self.env.now}")

            self.env.process(self.prep_order(car_id, car_id)) # Passing car_id as order for simplicity in prep function


        except simpy.Interrupt:
            print(f"Car {car_id} blocked at order queue at {self.env.now}") # Order Queue block not specifically tracked now, but could be added if needed.
            return # No specific blocking metric incremented here in simplified version, can add if needed.

        # --- Stage 3: Payment Queue ---
        enter_payment_queue_time = self.env.now
        try:
            yield self.payment_queue.put(car_id) # Enter Payment Queue
            self.metrics['wait_times_payment_queue'][-1] = self.env.now - enter_payment_queue_time
            print(f"Car {car_id} entered payment queue at {self.env.now}")

            # --- Stage 4: Payment and Pickup ---
            with self.payment_window.request() as request:
                yield request
                yield self.payment_queue.get()
                print(f"Car {car_id} began payment at {self.env.now}")
                payment_start_time = self.env.now

                payment_time = self.config.PAYMENT_TIME * random.uniform(0.9, 1.1) # Variable payment time
                yield self.env.timeout(payment_time)
                print(f"Car {car_id} finished payment at {self.env.now}")


        except simpy.Interrupt:
            print(f"Car {car_id} blocked at payment queue at {self.env.now}")
            self.metrics['cars_blocked_payment_queue'] += 1 # Increment payment queue blocking metric
            return

        # --- Stage 5: Wait for order prep (Simplified - No event needed now as order is just a placeholder) ---
        yield self.order_ready_events[car_id] # Still need to wait for order prep to finish before completion
        del self.order_ready_events[car_id]
        print(f"Car {car_id} order ready at {self.env.now}")

        # --- Completion ---
        self.metrics['total_times'][-1] = self.env.now - arrival_time
        self.metrics['cars_served'] += 1
        print(f"Car {car_id} completed at {self.env.now}")

    def prep_order(self, car_id, order): # Order is just car_id now - simplified
        with self.order_prep.request() as req:
            yield req
            prep_time = self.config.PREP_TIME * random.uniform(0.8, 1.2) # Variable prep time
            yield self.env.timeout(prep_time)
            self.order_ready_events[car_id].succeed()

def car_arrivals(env, drive_through):
    car_id = 0
    while True:
        car_id += 1
        drive_through.order_ready_events[car_id] = env.event()
        env.process(drive_through.process_car(car_id))
        yield env.timeout(3600 / drive_through.config.CARS_PER_HOUR) # Evenly distributed arrivals based on cars per hour (in seconds)

def run_simulation(config):
    print("Starting simulation...")
    env = simpy.Environment()
    drive_through = DriveThrough(env, config)
    env.process(car_arrivals(env, drive_through))
    print("Car arrivals process started...")
    env.run(until=config.SIMULATION_TIME)
    print("Simulation completed.")
    return drive_through.metrics

def analyze_results(metrics, config):
    if not metrics['car_ids']:
        return {
            'Cars Served': 0,
            'Cars Blocked (Payment Queue)': 0, # Adjusted metric name
            'Throughput (cars/hour)': 0.0,
            'Avg Wait Ordering Queue (min)': 0.0, # Adjusted metric name
            'Avg Wait Payment Queue (min)': 0.0, # Adjusted metric name
            'Avg Total Time (min)': 0.0,
        }, px.histogram(), px.histogram(),pd.DataFrame()

    df = pd.DataFrame({
        'Car ID': metrics['car_ids'],
        'Wait Time Ordering Queue (min)': metrics['wait_times_ordering_queue'], # Adjusted column name
        'Wait Time Payment Queue (min)': metrics['wait_times_payment_queue'],   # Adjusted column name
        'Total Time (min)': metrics['total_times']
    })

    avg_wait_ordering_queue = df['Wait Time Ordering Queue (min)'].mean() # Adjusted variable name
    avg_wait_payment_queue = df['Wait Time Payment Queue (min)'].mean()   # Adjusted variable name
    avg_total_time = df['Total Time (min)'].mean()
    throughput = metrics['cars_served'] / config.SIMULATION_TIME * 60

    results = {
        'Cars Served': metrics['cars_served'],
        'Cars Blocked (Payment Queue)': metrics['cars_blocked_payment_queue'], # Adjusted metric name
        'Throughput (cars/hour)': f"{throughput:.2f}",
        'Avg Wait Ordering Queue (min)': f"{avg_wait_ordering_queue:.2f}", # Adjusted metric name
        'Avg Wait Payment Queue (min)': f"{avg_wait_payment_queue:.2f}",   # Adjusted metric name
        'Avg Total Time (min)': f"{avg_total_time:.2f}",
    }

    fig_wait_order_queue = px.histogram(df, x='Wait Time Ordering Queue (min)', nbins=20, title='Distribution of Wait Times at Order Queue') # Adjusted chart title and column
    fig_wait_payment_queue = px.histogram(df, x='Wait Time Payment Queue (min)', nbins=20, title='Distribution of Wait Times at Payment Queue') # Adjusted chart title and column
    fig_total = px.histogram(df, x='Total Time (min)', nbins=20, title='Distribution of Total Time in System')

    return results, fig_wait_order_queue, fig_wait_payment_queue, fig_total, df

# --- Streamlit App ---
st.set_page_config(page_title="Simplified Drive-Through Simulation", page_icon=":car:", layout="wide")
st.title("Simplified Drive-Through Simulation")
st.write("""
This app simulates a simplified single-lane drive-through service.
Adjust the parameters in the sidebar and click 'Run Simulation' to see the results.
""")

# --- Sidebar (Inputs) ---
with st.sidebar:
    st.header("Simulation Parameters")

    # Initialize session state variables if they don't exist
    if 'cars_per_hour' not in st.session_state:
        st.session_state.cars_per_hour = 30.0
    if 'order_time' not in st.session_state:
        st.session_state.order_time = 1.0
    if 'prep_time' not in st.session_state:
        st.session_state.prep_time = 5.0
    if 'payment_time' not in st.session_state:
        st.session_state.payment_time = 1.0
    if 'order_queue_capacity' not in st.session_state:
        st.session_state.order_queue_capacity = 5
    if 'payment_queue_capacity' not in st.session_state:
        st.session_state.payment_queue_capacity = 8
    if 'simulation_time' not in st.session_state:
        st.session_state.simulation_time = 600

    # Use st.session_state to store and retrieve widget values
    cars_per_hour = st.number_input("Cars per Hour", min_value=1.0, max_value=200.0, value=st.session_state.cars_per_hour, step=1.0, format="%.1f", key="cars_per_hour")
    order_time = st.number_input("Order Time (min)", min_value=0.1, max_value=10.0, value=st.session_state.order_time, step=0.1, format="%.1f", key="order_time")
    prep_time = st.number_input("Preparation Time (min)", min_value=0.1, max_value=20.0, value=st.session_state.prep_time, step=0.1, format="%.2f", key="prep_time")
    payment_time = st.number_input("Payment Time (min)", min_value=0.1, max_value=5.0, value=st.session_state.payment_time, step=0.1, format="%.1f", key="payment_time")
    order_queue_capacity = st.number_input("Order Queue Capacity", min_value=1, max_value=100, value=st.session_state.order_queue_capacity, step=1, key="order_queue_capacity")
    payment_queue_capacity = st.number_input("Payment Queue Capacity", min_value=1, max_value=100, value=st.session_state.payment_queue_capacity, step=1, key="payment_queue_capacity") # Renamed label for clarity
    simulation_time = st.number_input("Simulation Time (min)", min_value=1, max_value=1440, value=st.session_state.simulation_time, step=1, key="simulation_time")

    if st.button("Run Simulation"):
        config = Config(cars_per_hour, order_time, prep_time, payment_time, order_queue_capacity, payment_queue_capacity, simulation_time) # Adjusted config parameters
        metrics = run_simulation(config)
        results, fig_wait_order_queue, fig_wait_payment_queue, fig_total, df = analyze_results(metrics, config) # Adjusted result variables

# --- Main Area (Results) ---
st.header("Simulation Results")

if 'metrics' in locals():
    st.dataframe(df)  # Show raw data

    # Display metrics in columns
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Cars Served", results['Cars Served'])
        st.metric("Cars Blocked (Payment Queue)", results['Cars Blocked (Payment Queue)']) # Adjusted metric label
    with col2:
        st.metric("Throughput (cars/hour)", results['Throughput (cars/hour)'])
        st.metric("Avg Wait Ordering Queue (min)", results['Avg Wait Ordering Queue (min)']) # Adjusted metric label
    with col3:
        st.metric("Avg Wait Payment Queue (min)", results['Avg Wait Payment Queue (min)']) # Adjusted metric label
        st.metric("Avg Total Time (min)", results['Avg Total Time (min)'])

    st.plotly_chart(fig_wait_order_queue, use_container_width=True) # Adjusted chart variable
    st.plotly_chart(fig_wait_payment_queue, use_container_width=True) # Adjusted chart variable
    st.plotly_chart(fig_total, use_container_width=True)
