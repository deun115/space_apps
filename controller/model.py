import os
import torch
import gc
import tensorflow as tf
import numpy as np
from sklearn.preprocessing import StandardScaler
from controller.cnn_classification_model import OneDCNNClassificationModel

# h5 모델 불러오기
def load_h5_model():
    try:
        # 모델 파일이 존재하는지 확인
        if not os.path.exists('home/yang1115/models/event_time_finder.h5'):
            raise FileNotFoundError('Model does not exist')
        
        # 모델 로드
        model = tf.keras.models.load_model(
            'home/yang1115/models/event_time_finder.h5', 
            custom_objects={'mse': tf.keras.losses.MeanSquaredError()}
        )
    
        return model

    except Exception as e:
        print(f'Error loading h5 model: {e}')
        return None

# pytorch 모델 불러오기
def load_pth_model(model_path):
    try:
        # 모델 파일이 존재하는지 확인
        if not os.path.exists(model_path):
            raise FileNotFoundError('Model does not exist')

        model = OneDCNNClassificationModel(input_channels=6000)
        model.load_state_dict(torch.load(model_path, map_location=torch.device('cpu'), weights_only=True))
        model.eval()

        # 메모리 정리
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        return model

    except Exception as e:
        print(f'Error loading pth model: {e}')
        return None
    
# classification 예측 진행
# Velocity가 가장 높은 top 3 (max)만 반환
# 일정 거리 내에 뭉쳐있으면 그 중 가장 높은 것만 반환
def predict_classification(velocity, sampling_rate):
    # Classification 모델 클래스 정의
    model_classification = load_pth_model('home/yang1115/models/original_seismic_classifier.pth')

    # 데이터 slicing 길이
    segment_length = 6000

    # segment_length 크기로 나눠서 classification 예측 진행
    classified_segments = []
    for start_offset in [0, segment_length // 2]:
        num_segments = int(np.ceil((len(velocity) - start_offset) / segment_length))
        for i in range(num_segments):
            start_index = start_offset + i * segment_length
            end_index = start_index + segment_length
            segment = velocity[start_index:end_index]
            
            # 끝부분 패딩 (0으로)
            if len(segment) < segment_length:
                continue
            
            # 모델을 사용하여 예측값 생성
            segment = torch.tensor(segment).float().unsqueeze(0)
            with torch.no_grad():
                outputs = model_classification(segment)
                predicted_label = torch.argmax(outputs, dim=1).item()
                if predicted_label == 1:
                    classified_segments.append((start_index / sampling_rate, end_index / sampling_rate))

    # 겹쳐있는 예측 구간 정리 - 겹친 구간만 제거
    non_overlapping_segments = []
    if classified_segments:
        classified_segments = sorted(classified_segments, key=lambda x: x[0])
        current_start, current_end = classified_segments[0]
        non_overlapping_segments.append((current_start, current_end))
        for start, end in classified_segments[1:]:
            if start < current_end:  # 겹치는 경우만 제거
                current_end = max(current_end, end)
                non_overlapping_segments[-1] = (current_start, current_end)
            else:
                non_overlapping_segments.append((start, end))
                current_start, current_end = start, end

    # 각 예측 구간에 대해 최대 velocity 값을 계산하고 저장
    segment_max_velocities = []
    for start, end in non_overlapping_segments:
        start_index = int(start * sampling_rate)
        end_index = start_index + segment_length * 3  # 시작부터 18000개의 데이터포인트 확인
        
        if end_index < len(velocity):
            segment = velocity[start_index:end_index]
        else:
            segment = velocity[start_index:]  # 남은 데이터를 끝까지 사용

        if len(segment) > 0:  # Ensure segment is not empty
            max_velocity = np.max(segment)
        else:
            max_velocity = 0

        segment_max_velocities.append((start, end, max_velocity))
    
    # 주변 +-48000칸 내에서 최대 velocity를 가지는 범위만 남기기
    final_segments = []
    for i, (start, end, max_velocity) in enumerate(segment_max_velocities):
        start_index = int(start * sampling_rate)
        surrounding_start_index = max(0, start_index - segment_length * 6)
        surrounding_end_index = min(len(velocity), start_index + segment_length * 6)
        is_max_in_surrounding = True
        for j, (other_start, other_end, other_max_velocity) in enumerate(segment_max_velocities):
            if i != j:
                other_start_index = int(other_start * sampling_rate)
                if surrounding_start_index <= other_start_index <= surrounding_end_index:
                    if other_max_velocity > max_velocity:
                        is_max_in_surrounding = False
                        break
        if is_max_in_surrounding:
            final_segments.append((start, end, max_velocity))
    
    # 최대 velocity 값 기준으로 상위 3개의 구간만 남기기
    final_segments = sorted(final_segments, key=lambda x: x[2], reverse=True)
    top_segments = final_segments[:3]

    # 상위 3개 구간의 길이가 6000인지 확인하고 자르기
    corrected_segments = []
    for start, end, max_velocity in top_segments:
        segment_length_check = int((end - start) * sampling_rate)
        if segment_length_check != segment_length:
            end = start + (segment_length / sampling_rate)  # 시작점 기준으로 6000으로 자르기
        corrected_segments.append((start, end, max_velocity))

    return corrected_segments

# 데이터 예측
def predict(velocity, times, sampling_rate):
    # Classification 예측 진행
    corrected_segments = predict_classification(velocity, sampling_rate)

    # 분류된 모델 h5에 맞게 전처리
    # selected_values = np.array(a)
    # scaler = StandardScaler()
    # scaler.fit(v)
    # test_scaled = scaler.transform(v.reshape(-1, v.shape[-1])).reshape(v.shape)

    # # 이벤트 모델 로드
    # model_h5 = load_h5_model()

    # print(len(test_scaled[0]))

    # # 모델 있으면 예측 진행
    # # 모델 없으면 None 반환
    # if model_h5:
    #     predictions = model_h5.predict(test_scaled)
    #     # return predictions.flatten()
    # else:
    #     print('Model could not be loaded.')
    #     return None
    
    # print(predictions.flatten()[ind[0]])
    # print(v[ind[0]][0], v[ind[0]][-1])
    # print(t[ind[0]])
    # # print(t[ind[0]][0], t[ind[0]][-1])

    return corrected_segments # a, predictions.flatten()[ind]