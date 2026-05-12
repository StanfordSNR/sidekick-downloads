# notebook

## Setup

Setup virtual environment:

```
cd $SIDEKICK_HOME
mkdir figures
virtualenv -p python3 env
source env/bin/activate
```

Install Python dependencies:

```
pip install jupyterlab
pip install matplotlib
pip install pandas
```

## Jupyter notebook

In the remote server:

```
tmux
source env/bin/activate
jupyter lab --no-browser
```

In a separate shell, forward the SSH port to the local machine:

```
ssh -L 8888:localhost:8888 <USER>@<HOST>
```

In the local machine, copy and paste the URL as instructed:

```
http://localhost:8888/tree?token=<TOKEN>
```

Click any notebook to replicate experiments.

## Troubleshooting

Make sure that the notebook can execute commands as root. 

Check the output logs in `data/` for specific errors. Each experiment produces stdout and stderr logs for the hosts and, if applicable, proxy/router.
