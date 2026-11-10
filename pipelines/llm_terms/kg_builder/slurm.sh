#!/bin/bash
#SBATCH --job-name=kg-pipeline
#SBATCH --output=logs/kg_pipeline_%j.out
#SBATCH --error=logs/kg_pipeline_%j.err
#SBATCH --time=4:00:00
#SBATCH --cpus-per-task=16
#SBATCH --mem=26G
#SBATCH --nodes=1
#SBATCH --ntasks=1


python kg_builder_fast.py