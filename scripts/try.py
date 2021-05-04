import rsconnect.api as rscapi
from dotenv import load_dotenv

# define CONNECT_SERVER and CONNECT_API_KEY env vars in the ".env" file
load_dotenv()

myrsc_raw = rscapi.rstudio_connect()

myrsc = rscapi.RSConnect(myrsc_raw)


inst_static = myrsc.inst_static()

inst_shiny = myrsc.inst_shiny()


procs = myrsc.procs()
