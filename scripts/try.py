import rsconnect.api as rscapi
from dotenv import load_dotenv

load_dotenv()

myrsc_raw = rscapi.rstudio_connect()

myrsc = rscapi.RSConnect(myrsc_raw)


inst_static = myrsc.inst_static()

inst_shiny = myrsc.inst_shiny()


procs = myrsc.procs()
