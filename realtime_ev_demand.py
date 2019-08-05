import simpy
from scipy import stats
from datetime import datetime, timedelta
import pickle
import time

POWER_FACTOR = 0.98
POWER_DEMAND_WHEN_CHARGING = 3.6*POWER_FACTOR
CHARGE_PER_SEGMENT = 2
NUM_CARS = 3
#DAYS = 1
GAP = 0 # minimum time between successive chargings
EPOCH = time.time()


#Unpickle the pickled probability data
with open('normalized_probabilities_zeroed.pickle', 'rb') as fp:
    connection_properties_dict = pickle.load(fp)


##probability daily connection
pk_weekend_count = connection_properties_dict['count_prob_end']
pk_weekday_count = connection_properties_dict['count_prob_day']


xk_connection_time = connection_properties_dict['connection_time_step']
pk_weekend_1 = connection_properties_dict['connection_time_end_1']
pk_weekend_2 = connection_properties_dict['connection_time_end_2']
pk_weekday_1 = connection_properties_dict['connection_time_day_1']
pk_weekday_2 = connection_properties_dict['connection_time_day_2']

#SOC calculation
xk_chargelevel = connection_properties_dict['soc_unit_level']
pk_weekend_1_initial = connection_properties_dict['soc_end_initial_1']
pk_weekend_2_initial = connection_properties_dict['soc_end_initial_2']
pk_weekday_1_initial = connection_properties_dict['soc_day_initial_1']
pk_weekday_2_initial = connection_properties_dict['soc_day_initial_2']

pk_weekend_1_final = connection_properties_dict['soc_end_final_1']
pk_weekend_2_final = connection_properties_dict['soc_end_final_2']
pk_weekday_1_final = connection_properties_dict['soc_day_final_1']
pk_weekday_2_final = connection_properties_dict['soc_day_final_2']

## Random variable generators

## Number of daily connections
number_of_connection_end_rv_generator = stats.rv_discrete(values =([1,2], pk_weekend_count))
number_of_connection_day_rv_generator = stats.rv_discrete(values =([1,2], pk_weekday_count))

## charge duration
initial_day_1_soc_rv_generator = stats.rv_discrete(values=(xk_chargelevel,pk_weekday_1_initial))
initial_day_2_soc_rv_generator = stats.rv_discrete(values=(xk_chargelevel,pk_weekday_2_initial))
initial_end_1_soc_rv_generator = stats.rv_discrete(values=(xk_chargelevel,pk_weekend_1_initial))
initial_end_2_soc_rv_generator = stats.rv_discrete(values=(xk_chargelevel,pk_weekend_2_initial))

final_day_1_soc_rv_generator = stats.rv_discrete(values=(xk_chargelevel,pk_weekday_1_final))
final_day_2_soc_rv_generator = stats.rv_discrete(values=(xk_chargelevel,pk_weekday_2_final))
final_end_1_soc_rv_generator = stats.rv_discrete(values=(xk_chargelevel,pk_weekend_1_final))
final_end_2_soc_rv_generator = stats.rv_discrete(values=(xk_chargelevel,pk_weekend_2_final))

## Daily connection times
connection_time_end_1_rv_generator = stats.rv_discrete(values=(xk_connection_time, pk_weekend_1))
connection_time_end_2_rv_generator = stats.rv_discrete(values=(xk_connection_time, pk_weekend_2))
connection_time_day_1_rv_generator = stats.rv_discrete(values=(xk_connection_time, pk_weekday_1))
connection_time_day_2_rv_generator = stats.rv_discrete(values=(xk_connection_time, pk_weekday_2))



#Assuming simulation start on Monday 00:00:00
def is_weekend(minutes_passed):
    d = datetime.now()+timedelta(minutes = minutes_passed)
    if d.weekday()>4:
        return True
    else:
        return False

#format minutes to HH:MM
def format_minutes(minutes_passed):
    return str(timedelta(minutes=minutes_passed))[:-3]

#minutes left in a day
def minutes_left_in_the_day(minutes_passed):
    minutes_left = (24*60)-(minutes_passed%(24*60))
    return minutes_left

def number_of_daily_connections(minutes_passed):
    if is_weekend(minutes_passed):
        rv_gen = number_of_connection_end_rv_generator
    else:
        rv_gen = number_of_connection_day_rv_generator
    return rv_gen.rvs(size=1)[0]


def charge_duration_calculation(minutes_passed,count):
    #print('duration calculation ')
    #initial SOC calculation
    if count==1:
        if is_weekend(minutes_passed):
            rv_gen = initial_end_1_soc_rv_generator
        else:
            rv_gen = initial_day_1_soc_rv_generator
    else:
        if is_weekend(minutes_passed):
            rv_gen = initial_end_2_soc_rv_generator
        else:
            rv_gen = initial_day_2_soc_rv_generator

    initial_soc = rv_gen.rvs(size=1)[0]
    if initial_soc == 12:
        return 60
    #print('initi ',initial_soc)
    #Final SOC calculation
    if count==1:
        if is_weekend(minutes_passed):
            rv_gen = final_end_1_soc_rv_generator
        else:
            rv_gen = final_day_1_soc_rv_generator
    else:
        if is_weekend(minutes_passed):
            rv_gen = final_end_2_soc_rv_generator
        else:
            rv_gen = final_day_2_soc_rv_generator

    final_soc = 0
    while final_soc<=initial_soc:
        final_soc= rv_gen.rvs(size=1)[0]
    #print('final',final_soc)
    duration = ((final_soc-initial_soc)*CHARGE_PER_SEGMENT)/(3.6*POWER_FACTOR/60)

    #print(format_minutes(duration))
    return duration

def daily_connection_time_calculation(minutes_passed,connection_number):
    if connection_number==1:
        if is_weekend(minutes_passed):
            rv_gen = connection_time_end_1_rv_generator
        else:
            rv_gen = connection_time_day_1_rv_generator
    else:
        if is_weekend(minutes_passed):
            rv_gen = connection_time_end_2_rv_generator
        else:
            rv_gen = connection_time_day_2_rv_generator

    next_connection_time = int(rv_gen.rvs(size=1)[0])
    return next_connection_time
    # time = random.randint(2*60,20*60)
    # return time

class EVClass:
    def __init__(self, env, name):
        self.env = env
        self.name = name
        self.connection_clock_times = [0,0]
        self.power_demand = 0
        self.last_balance_charging_clock_time = 0

        # Start the run and monitor process everytime an instance is created.
        self.action = env.process(self.run())
        self.monitor_process = env.process(self.monitor_demand(env))

    def run(self):
        while True:
            #calculate number of connection
            number_of_connections = number_of_daily_connections(self.env.now)
            #print("number_of_connections: {}".format(number_of_connections))

            #left over charging from last day using self.last_balance_charging_clock_time
            yield self.env.timeout(self.last_balance_charging_clock_time)
            self.power_demand = 0

            yield self.env.process(self.charging_process(number_of_connections))
    def charging_process(self,connection_count):

        if connection_count == 1:
            #calculate connection time
            connection_start_clock_time = self.connection_clock_time_calculation(connection_count)
            yield self.env.timeout(connection_start_clock_time-self.last_balance_charging_clock_time)
        else:
            #calculate connection time
            connection_start_clock_time = self.connection_clock_time_calculation(connection_count)
            yield self.env.process(self.additional_charging(connection_start_clock_time))
        #Charging time    
        balance_time_duration = yield self.env.process(self.charge(connection_count))
        #print("in main run, with balance_time {} hours".format(balance_time/60))

        #if charging end before midnight go to next day
        if balance_time_duration>=0:
            self.power_demand  = 0
            self.last_balance_charging_clock_time = 0
            yield self.env.timeout(balance_time_duration)
            #print('day ends here')
        #else wait for the day to end and assign balance charging time to self.last_balance_charging_clock_time
        else:
            #print('day ends here for left over')
            self.last_balance_charging_clock_time = -balance_time_duration

    def additional_charging(self, end_clock_time):
        #calculate connection start time such that it is between balance time and second connection start time
        connection_start_clock_time = 0
        while not end_clock_time>connection_start_clock_time>(self.last_balance_charging_clock_time+GAP):
            connection_start_clock_time = self.connection_clock_time_calculation(1)

        duration = end_clock_time
        if (end_clock_time-connection_start_clock_time)>40:
            while connection_start_clock_time+duration>(end_clock_time-GAP):
                duration = charge_duration_calculation(self.env.now,1)
                #print("stuck here")
        else:
            duration = 0
        #wait till first connection start time
        yield self.env.timeout(connection_start_clock_time-self.last_balance_charging_clock_time)

        #start charging
        #print("start charging 1 of 2 at: {}".format(format_minutes(self.env.now)))
        self.power_demand = POWER_DEMAND_WHEN_CHARGING
        yield self.env.timeout(duration)

        #stop charging and wait till second connection
        self.power_demand = 0
        yield self.env.timeout(end_clock_time-(connection_start_clock_time+duration))
            
    def charge(self,count):
        self.power_demand = POWER_DEMAND_WHEN_CHARGING
        #print("charging starts at: {}".format(format_minutes(self.env.now)))
        duration = charge_duration_calculation(self.env.now,count)
        #print("charge duration {}".format(format_minutes(duration)))
        balance_time_duration = (24*60)-(self.connection_clock_times[count-1]+duration)
        #positive balance time means charging ends before midnight
        if balance_time_duration>=0:
            #print("charging at {} ends befor midnight".format(format_minutes(self.env.now)))
            #print("connection time {}".format(format_minutes(self.connection_times[count-1])))
            yield self.env.timeout(duration)
            return balance_time_duration
        else:
            #charge till midnight and return the balance time
            #print("charging at till midnight from {}, left on tomorrow {}".format(format_minutes(self.env.now),balance_time))
            yield self.env.timeout((24*60)-self.connection_clock_times[count-1])
            return balance_time_duration


    def connection_clock_time_calculation(self,count):
        if self.last_balance_charging_clock_time==0:
            clock_time = daily_connection_time_calculation(self.env.now,count)

        else:
            clock_time = 0
            while clock_time<self.last_balance_charging_clock_time:
                clock_time = daily_connection_time_calculation(self.env.now,count)
        
        self.connection_clock_times[count-1] = clock_time
        return clock_time



    def monitor_demand(self,env):
        i = 2
        while True:
            seconds_passed = (env.now)*60+EPOCH
            print("{}, {}, {}".format(self.name,self.power_demand, seconds_passed))
            # output_lines.append("Power demand by {} on {} = {}\n".format(self.name,format_minutes(minutes_passed),self.power_demand))
            # sheet.cell(row=i,column=1).value = format_minutes(minutes_passed)
            # sheet.cell(row=i,column=int(self.name[5:])+1).value = self.power_demand
            # i+=1
            yield env.timeout(1)

# ## main starts here
# wb = openpyxl.load_workbook('demand_output_single_connection.xlsx')
# sheet = wb.active

# output_lines = []
env = simpy.rt.RealtimeEnvironment(factor=60)
cars = [EVClass(env, 'ev.ev{}'.format(i+1)) for i in range(NUM_CARS)]
#print('starting simulation')
env.run()
# print('writing to file')
# # wb.save('output.xlsx')
# with open('output_single_connection.txt','w') as fp:
#     fp.writelines(output_lines)
# print('finished')
