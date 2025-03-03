from typing import List
from utils import load_hf_model
from itertools import combinations
import numpy as np
from tqdm import tqdm
from datasets import load_from_disk, concatenate_datasets
from transformers import T5EncoderModel, set_seed
import torch
import torch.nn.functional as F
from sklearn.metrics import roc_auc_score, davies_bouldin_score, silhouette_score

from metrics import *
from generation import *
from model_list import *

@torch.no_grad()
def evaluate_cl(
    model_list,
    contrastive_set,
    model_name_or_path: str,
):  
    model = T5EncoderModel.from_pretrained(
        model_name_or_path,
        # device_map='auto',
        output_hidden_states=True,
        ignore_mismatched_sizes=True,
        )
    
    model = model.eval()
    
    # l = len(test_trigger_set)
    simlarity_marices = [] # (len(test_trigger_set), 18, 18)
    
    for sample in tqdm(contrastive_set):
        batch_input_ids = sample['input_ids'] # (18, seq_length)
        batch_attention_mask = sample['attention_mask']
        inputs = {
            'input_ids' : torch.tensor(batch_input_ids),
            'attention_mask' : torch.tensor(batch_attention_mask),
        }
        last_hidden_states = model(**inputs).last_hidden_state # (18, seq_length, hidden_states)
        aggregated_hidden_states = torch.sum(last_hidden_states, dim=1) # (18, hidden_states)
        # aggregated_hidden_states = torch.squeeze(last_hidden_states[:, 0, :]) # (18, hidden_states)
        aggregated_hidden_states = F.normalize(aggregated_hidden_states, dim=-1)
        simlarity_marix = torch.matmul(aggregated_hidden_states, aggregated_hidden_states.T) # (18, 18)
        simlarity_marices.append(simlarity_marix)
    
    # Compute the success rate.
    print(f"Computing the success rate...")
    number = len(simlarity_marices)
    sr = np.zeros((len(model_list), ), dtype=int)
    for matrix in simlarity_marices:
        logits = matrix.detach().numpy()
        # llama family.
        for i in range(1, 4):
            # 0, 1, 2, 3, |4, 5, 6, 7, |8, 9, 10, 11
            # (varient, positive base model) pair and the (varient, negative base model). 
            if logits[0, i] >= max(logits[0, 4], logits[0, 8]):
                sr[i] += 1
        # qwen family. 
        for i in range(5, 8):
            if logits[4, i] >= max(logits[4, 0], logits[4, 8]):
                sr[i] += 1
        # mistral family. 
        for i in range(9, 11):
            if logits[8, i] >= max(logits[8, 0], logits[8, 4]):
                sr[i] += 1
    sr = sr / number
    
    simlarity_marices = torch.stack(simlarity_marices, dim=0)
    # print(simlarity_marices.shape)   

    mean_simlarity_matrix = torch.mean(simlarity_marices, dim=0)
    # print(mean_simlarity_matrix.shape)
    
    print(f"Start Evaluating...")
    
    # Compute the model numbers in each family.
    model_number_per_family = len(model_list) // 3
    model_number = len(model_list)
    original_model_index = range(0, model_number, model_number_per_family)
    
    # Llama Family.
    llama_labels = np.zeros(model_number)
    start = original_model_index[0]
    llama_labels[start: start + model_number_per_family] = 1
    print(f"Llama family labels: {llama_labels}")
    
    llama_pred_base = mean_simlarity_matrix.detach().numpy()[start,:]
    for i in range(start, start + model_number_per_family):
        # Obtain the i-th (suspect model) row of the simlarity matrix
        llama_pred = mean_simlarity_matrix.detach().numpy()[i,:]
        # Ignore suspect model itself. 
        llama_roc = roc_auc_score(y_true=np.delete(llama_labels, i), y_score=np.delete(llama_pred, i))
        llama_s_index = s_index(current_index=i, start=start, model_number_per_family=model_number_per_family, y_score=llama_pred_base)  
        llama_db_index = davies_bouldin_score(llama_pred.reshape(-1, 1), llama_labels)
        llama_silhouette_score = silhouette_score(llama_pred.reshape(-1, 1), llama_labels)
        current_model = model_list[i][model_list[i].rfind('/') + 1 : ]
        print(f"Suspect Model is {current_model}.")
        print(f"Extractor predict on current: {llama_pred}")
        print(f"Roc-auc score of the current: {llama_roc}")
        print(f"Success rate of the current: {sr[i] * 100}%")
        print(f"S-Index of the current: {llama_s_index}")
        print(f"Silhouette Score of the current: {llama_silhouette_score}")
        print(f"Davies-Bouldin Index of the current: {llama_db_index}")
        print(f"#############################################")
    
    # Qwen Family
    qwen_labels = np.zeros(model_number)
    start = original_model_index[1]
    qwen_labels[start: start + model_number_per_family] = 1
    print(f"Qwen family labels: {qwen_labels}")
    
    qwen_pred_base = mean_simlarity_matrix.detach().numpy()[start,:]
    for i in range(start, start + model_number_per_family):
        qwen_pred = mean_simlarity_matrix.detach().numpy()[i,:]
        qwen_roc = roc_auc_score(y_true=np.delete(qwen_labels, i), y_score=np.delete(qwen_pred, i))
        qwen_s_index = s_index(current_index=i, start=start, model_number_per_family=model_number_per_family, y_score=qwen_pred_base)
        qwen_db_index = davies_bouldin_score(qwen_pred.reshape(-1, 1), qwen_labels)
        qwen_silhouette_score = silhouette_score(qwen_pred.reshape(-1, 1), qwen_labels)
        current_model = model_list[i][model_list[i].rfind('/') + 1 : ]
        print(f"Suspect Model is {current_model}.")
        print(f"Extractor predict on current: {qwen_pred}")
        print(f"Roc-auc score of the current: {qwen_roc}")
        print(f"Success rate of the current: {sr[i] * 100}%")
        print(f"S-Index of the current: {qwen_s_index}")
        print(f"Silhouette Score of the current: {qwen_silhouette_score}")
        print(f"Davies-Bouldin Index of the current: {qwen_db_index}")
        print(f"#############################################")
    
    # Mistral Family.
    mistral_labels = np.zeros(model_number)
    start = original_model_index[2]
    mistral_labels[start: start + model_number_per_family] = 1
    print(f"Mistral family labels: {mistral_labels}")
    
    mistral_pred_base = mean_simlarity_matrix.detach().numpy()[start,:]
    for i in range(start, start + model_number_per_family):
        mistral_pred = mean_simlarity_matrix.detach().numpy()[i,:]
        mistral_roc = roc_auc_score(y_true=np.delete(mistral_labels, i), y_score=np.delete(mistral_pred, i))
        mistral_s_index = s_index(current_index=i, start=start, model_number_per_family=model_number_per_family, y_score=mistral_pred_base)
        mistral_silhouette_score = silhouette_score(mistral_pred.reshape(-1, 1), mistral_labels)
        mistral_db_index = davies_bouldin_score(mistral_pred.reshape(-1, 1), mistral_labels)
        current_model = model_list[i][model_list[i].rfind('/') + 1 : ]
        print(f"Suspect Model is {current_model}.")
        print(f"Extractor predict on current: {mistral_pred}")
        print(f"Roc-auc score of the current: {mistral_roc}")
        print(f"Success rate of the current: {sr[i] * 100}%")
        print(f"S-Index score of the current: {mistral_s_index}")
        print(f"Silhouette Score of the current: {mistral_silhouette_score}")
        print(f"Davies-Bouldin Index of the current: {mistral_db_index}")
        print(f"#############################################")
    
    # # Print the success rate.
    # for i in range(len(model_list)):
    #     if i != 0 and i != 4 and i != 8:
    #         print(f"{model_list[i][model_list[i].rfind('/') + 1 : ]}'s success rate: {sr[i] * 100}%")
    #         print(f"#############################################")

@torch.no_grad()
def evaluate_cl_unseen(
    # trajectory_set_train, 
    trajectory_set_unseen, 
    tokenizer, 
    model_name_or_path: str, 
):
    # # Select the base models' trajectory.
    # base_trajectory = trajectory_set_train.select(
    #     list(range(0, 600)) + 
    #     list(range(10 * 600, 11 * 600)) + 
    #     list(range(20 * 600, 21 * 600))
    # )
    
    # Construct the fianl dataset.
    # dataset = concatenate_datasets(trajectory_set_unseen)
    contrastive_set = construct_contrastive_dataset(
        tokenizer=tokenizer, 
        raw_data=trajectory_set_unseen, 
        model_list=MODEL_LIST_UNSEEN
    )
    
    model = T5EncoderModel.from_pretrained(
        model_name_or_path,
        # device_map='auto',
        output_hidden_states=True,
        ignore_mismatched_sizes=True,
    )
    
    model = model.eval()
    
    simlarity_marices = []
    # Obtain the similarity matrix.
    for sample in tqdm(contrastive_set):
        batch_input_ids = sample['input_ids']
        batch_attention_mask = sample['attention_mask']
        inputs = {
            'input_ids' : torch.tensor(batch_input_ids),
            'attention_mask' : torch.tensor(batch_attention_mask),
        }
        last_hidden_states = model(**inputs).last_hidden_state
        aggregated_hidden_states = torch.sum(last_hidden_states, dim=-1)
        # aggregated_hidden_states = torch.squeeze(last_hidden_states[:, 0, :]) # (18, hidden_states)
        aggregated_hidden_states = F.normalize(aggregated_hidden_states, dim=-1)
        simlarity_marix = torch.matmul(aggregated_hidden_states, aggregated_hidden_states.T)
        simlarity_marices.append(simlarity_marix)
    
    simlarity_marices = torch.stack(simlarity_marices, dim=0)
    # print(simlarity_marices.shape)   

    mean_simlarity_matrix = torch.mean(simlarity_marices, dim=0)
    # print(mean_simlarity_matrix.shape)
    
    print(f"Start Evaluating...")
    llama3_2_labels = [1, 1, 0, 0, 0]
    for i in range(0, 3):
        llama3_2_pred = mean_simlarity_matrix.detach().numpy()[i,:]
        llama3_2_pred_ = np.delete(llama3_2_pred, i)
        print(llama3_2_pred_)
        llama3_2_auc = roc_auc_score(y_true=llama3_2_labels, y_score=llama3_2_pred_)
        # llama3_2_silhouette_score = silhouette_score(llama3_2_pred.reshape(-1, 1), llama3_2_labels)
        current_model = MODEL_LIST_UNSEEN[i][MODEL_LIST_UNSEEN[i].rfind('/') + 1 : ]
        print(f"Current Model is: {current_model}")
        print(f"Extractor predict on current: {llama3_2_pred}")
        print(f"Roc-auc score of the current: {llama3_2_auc}")
        # print(f"Silhouette Score of the current: {llama3_2_silhouette_score}")
        print(f"#############################################")
        
def cross_fold_evaluation(
    model_path, 
    fold: int, 
    seed: int,
    optimized_set: None, 
):
    trajectory_set = load_from_disk('./data/trajectory_set')
    
    set_seed(seed=seed)
    
    res, model_list_train, model_list_eval = get_cross_validation_datasets(
        trajectory_set=trajectory_set,
        model_list=MODEL_LIST_TRAIN,
        fold=fold
    )
    
    train_set, eval_set = res['train'], res['eval']
    # tokenizer = AutoTokenizer.from_pretrained(model_path)
    tokenizer = AutoTokenizer.from_pretrained('/mnt/data/hf_models/t5-base')
    
    if optimized_set:
        indices = optimized_set['prompt_index']
        dataset = construct_contrastive_dataset(
            tokenizer=tokenizer,
            raw_data=eval_set,
            model_list=model_list_eval,
        ).select(indices)
        contrastive_dataset = ContrastiveDataset(dataset)
    else:
        contrastive_dataset = ContrastiveDataset(
            construct_contrastive_dataset(
                tokenizer=tokenizer,
                raw_data=eval_set,
                model_list=model_list_eval,
            )
        )
    
    # Utilize the optimized triggers. 
    
    evaluate_cl(
        model_list=model_list_eval,
        contrastive_set=contrastive_dataset,
        model_name_or_path=model_path, 
    )
        
if __name__ == '__main__':
    set_seed(42)
        
    # evaluate trajectories
    # trigger_set = load_from_disk('./data/final_trigger_set')
    
    # res = evaluate(trigger_set=trigger_set, model_list=MODEL_LIST)
    
    # distance_matrix_plot(result_dict=res,
    #                      save_dir='result.png')
    
    
    # evaluate cl classifier
    model_path = './metric_learning_models/0206_fold_2'
    optimized_set = load_from_disk('./data/optimized_trigger_set_llama_0')
    
    tokenizer = AutoTokenizer.from_pretrained(model_path)
    
    # evaluation on the train models.
    raw_data = load_from_disk('./data/trajectory_set')
    # cross_fold_evaluation(
    #     model_path=model_path, 
    #     fold=0, 
    #     seed=42,
    #     optimized_set=optimized_set
    #     # optimized_set=None, 
    # )
    
    trajectory_set_unseen = load_from_disk('./data/trajectory_set_unseen')
    evaluate_cl_unseen(
        # trajectory_set_train=raw_data, 
        trajectory_set_unseen=trajectory_set_unseen, 
        tokenizer=tokenizer, 
        model_name_or_path=model_path, 
    )