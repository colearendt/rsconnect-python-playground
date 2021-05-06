import rsconnect.api as rsc
from dotenv import load_dotenv

# define CONNECT_SERVER and CONNECT_API_KEY env vars in the ".env.prod" file
load_dotenv()

client = rsc.rstudio_connect()

inst_static = client.inst_static()
inst_shiny = client.inst_shiny()
procs = client.procs()
